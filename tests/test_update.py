import subprocess
import sys
from pathlib import Path

import pytest

from asset_frame.cli import UPDATE_STEP_NAMES, _update_steps, main
from asset_frame.update import (
    AlreadyRunning,
    Step,
    UpdateLock,
    load_env_file,
    notify_failure,
    run_steps,
    select_steps,
    summary,
)


def ok() -> None:
    return None


def boom() -> None:
    raise RuntimeError("network down")


def exit_with(message: str):  # type: ignore[no-untyped-def]
    def run() -> None:
        raise SystemExit(message)

    return run


def test_a_failed_step_does_not_stop_the_rest_and_is_reported() -> None:
    log: list[str] = []
    steps = [
        Step("fred", "collect", boom),
        Step("universe", "collect", exit_with("1 ticker failed")),
        Step("build-returns", "derive", ok),
        Step("backup", "backup", ok),
    ]
    results = run_steps(steps, report=log.append)
    assert [(r.name, r.status) for r in results] == [
        ("fred", "failed"), ("universe", "failed"), ("build-returns", "ok"), ("backup", "ok"),
    ]  # fmt: skip
    assert (
        "RuntimeError: network down" in results[0].detail and results[1].detail == "1 ticker failed"
    )
    assert "FAILED" in log[0]
    assert summary(results) == "update: 2 ok, 2 failed (fred, universe), 0 skipped"


def test_the_ledger_step_is_skipped_after_a_collection_failure() -> None:
    steps = [
        Step("fred", "collect", boom),
        Step("record-regime", "ledger", ok),
        Step("dashboard", "derive", ok),
    ]
    results = run_steps(steps, report=lambda _: None)
    assert [r.status for r in results] == ["failed", "skipped", "ok"]
    assert "collection" in results[1].detail


def test_a_derive_failure_does_not_block_the_ledger_step() -> None:
    steps = [Step("build-returns", "derive", boom), Step("record-regime", "ledger", ok)]
    assert [r.status for r in run_steps(steps, report=lambda _: None)] == ["failed", "ok"]


def test_a_clean_system_exit_counts_as_success() -> None:
    def clean() -> None:
        raise SystemExit(0)

    assert run_steps([Step("x", "derive", clean)], report=lambda _: None)[0].status == "ok"


def test_selecting_steps_keeps_their_order_and_rejects_unknown_names() -> None:
    steps = [Step(n, "derive", ok) for n in ("a", "b", "c")]
    assert [s.name for s in select_steps(steps, ["c", "a"])] == ["a", "c"]
    assert [s.name for s in select_steps(steps, None)] == ["a", "b", "c"]
    with pytest.raises(ValueError, match="unknown step: z"):
        select_steps(steps, ["z"])


def test_the_real_step_list_collects_before_it_derives_and_records() -> None:
    steps = _update_steps(__import__("datetime").date(2026, 11, 22), 75.0)
    assert tuple(s.name for s in steps) == UPDATE_STEP_NAMES
    groups = [s.group for s in steps]
    assert groups.index("ledger") > max(i for i, g in enumerate(groups) if g == "collect")
    assert groups.index("ledger") > groups.index("derive")


def test_dry_run_lists_steps_without_running_any(capsys: pytest.CaptureFixture[str]) -> None:
    main(["update", "--dry-run", "--steps", "fred,dashboard"])
    assert capsys.readouterr().out.splitlines() == ["fred (collect)", "dashboard (derive)"]


def test_an_unknown_step_name_stops_the_command() -> None:
    with pytest.raises(SystemExit, match="unknown step"):
        main(["update", "--dry-run", "--steps", "nope"])


def test_the_lock_blocks_a_live_run_and_replaces_a_stale_one(tmp_path: Path) -> None:
    path = tmp_path / "update.lock"
    with UpdateLock(path):
        assert path.read_text().strip().isdigit()
        with pytest.raises(AlreadyRunning), UpdateLock(path):
            pass
    assert not path.exists()  # released
    finished = subprocess.Popen([sys.executable, "-c", "pass"])
    finished.wait()
    path.write_text(str(finished.pid))  # a pid that no longer exists
    with UpdateLock(path):
        assert path.read_text() != str(finished.pid)
    path.write_text("not a pid")
    with UpdateLock(path):
        pass


def test_env_file_sets_only_missing_variables_and_returns_names_not_values(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\n\nTIINGO_API_KEY=abc123\nexport FRED_API_KEY='quoted'\nKRX_API_KEY=\n"
        'ECOS_API_KEY="dq"\nDATABASE_PATH=var/x.sqlite3\nnot a pair\n'
    )
    environ = {"DATABASE_PATH": "from-shell"}
    applied = load_env_file(env_file, environ)
    assert sorted(applied) == ["ECOS_API_KEY", "FRED_API_KEY", "TIINGO_API_KEY"]
    assert environ["TIINGO_API_KEY"] == "abc123" and environ["FRED_API_KEY"] == "quoted"
    assert environ["ECOS_API_KEY"] == "dq" and environ["DATABASE_PATH"] == "from-shell"
    assert "KRX_API_KEY" not in environ  # empty values are ignored
    assert "abc123" not in " ".join(applied)
    assert load_env_file(tmp_path / "missing", {}) == []


def test_failure_notification_names_steps_only_and_only_on_macos() -> None:
    calls: list[list[str]] = []

    def run(argv, **_):  # type: ignore[no-untyped-def]
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    notify_failure(["universe", "fred"], run=run, platform="darwin")
    assert "universe, fred" in calls[0][2] and calls[0][0] == "/usr/bin/osascript"
    notify_failure(["universe"], run=run, platform="linux")
    notify_failure([], run=run, platform="darwin")
    assert len(calls) == 1


def test_progress_file_counts_tickers_and_is_removed_when_the_run_ends(tmp_path: Path) -> None:
    from asset_frame import update

    path = tmp_path / "progress.json"
    seen: list[dict] = []

    def work() -> None:
        import json

        seen.append(json.loads(path.read_text()))  # step 1 just began: nothing done yet
        update.tick()
        seen.append(json.loads(path.read_text()))  # one of three tickers finished

    run_steps(
        [Step("universe", "collect", work, units=3), Step("dashboard", "derive", ok)],
        progress_path=path,
    )

    assert [s["percent"] for s in seen] == [0, 25]  # 0 of 4 units, then 1 of 4
    assert (
        seen[1]["step"] == "universe" and seen[1]["step_done"] == 1 and seen[1]["step_total"] == 3
    )
    assert not path.exists()
    update.tick()  # outside a run: harmless

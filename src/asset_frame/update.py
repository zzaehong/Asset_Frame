"""One command that refreshes everything for a scheduled run (ADR-0012).

Steps run in order; a failed step does not stop the rest, and the ledger step is skipped when any
collection step failed (a permanent record must not be built from stale data). `.env` values fill
in only variables that are not already set, and nothing here prints a value.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, MutableMapping, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Step:
    name: str
    group: str  # "collect" | "derive" | "ledger" | "backup"
    run: Callable[[], None]
    units: int = 1  # work items (tickers) the progress percentage counts for this step


@dataclass(frozen=True, slots=True)
class StepResult:
    name: str
    status: str  # "ok" | "failed" | "skipped"
    seconds: float
    detail: str = ""


def select_steps(steps: Sequence[Step], names: Sequence[str] | None) -> list[Step]:
    """All steps, or only the named ones in their normal order."""
    if not names:
        return list(steps)
    known = {step.name for step in steps}
    unknown = [name for name in names if name not in known]
    if unknown:
        raise ValueError(f"unknown step: {', '.join(unknown)} (known: {', '.join(sorted(known))})")
    return [step for step in steps if step.name in names]


def _failure_text(error: BaseException) -> str:
    return str(error.code) if isinstance(error, SystemExit) else f"{type(error).__name__}: {error}"


class Progress:
    """Writes `var/progress.json` so the Mac app can show a percentage while a run is live.

    shortcut: the percentage counts tickers and treats every other step as one unit, so it tracks
    time roughly (downloads dominate); it is not an ETA.
    """

    def __init__(self, path: Path | None, steps: Sequence[Step]) -> None:
        self.path = path
        self.steps = list(steps)
        self.total = max(1, sum(max(1, s.units) for s in steps))
        self.base = 0
        self.index = 0
        self.inside = 0

    def begin(self, index: int) -> None:
        self.index = index
        self.base = sum(max(1, s.units) for s in self.steps[:index])
        self.inside = 0
        self._write()

    def tick(self) -> None:
        self.inside = min(self.inside + 1, max(1, self.steps[self.index].units))
        self._write()

    def end_step(self) -> None:
        self.inside = max(1, self.steps[self.index].units)
        self._write()

    def clear(self) -> None:
        if self.path:
            self.path.unlink(missing_ok=True)

    def _write(self) -> None:
        if not self.path:
            return
        done = self.base + self.inside
        body = {
            "percent": min(100, done * 100 // self.total),
            "step": self.steps[self.index].name,
            "step_index": self.index + 1,
            "steps": len(self.steps),
            "step_done": self.inside,
            "step_total": max(1, self.steps[self.index].units),
        }
        with contextlib.suppress(OSError):  # progress is a courtesy; never fail a run over it
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(body), encoding="utf-8")
            temporary.replace(self.path)


_current: Progress | None = None


def tick() -> None:
    """Called once per ticker by a collection loop; a no-op outside `run_steps`."""
    if _current:
        _current.tick()


def run_steps(
    steps: Sequence[Step],
    *,
    report: Callable[[str], None] = print,
    clock: Callable[[], float] = time.monotonic,
    progress_path: Path | None = None,
) -> list[StepResult]:
    global _current  # noqa: PLW0603 - the collection loops report through tick()
    results: list[StepResult] = []
    collect_failed = False
    _current = Progress(progress_path, steps)
    try:
        return _run(steps, results, collect_failed, report, clock)
    finally:
        _current.clear()
        _current = None


def _run(
    steps: Sequence[Step],
    results: list[StepResult],
    collect_failed: bool,
    report: Callable[[str], None],
    clock: Callable[[], float],
) -> list[StepResult]:
    assert _current is not None
    for number, step in enumerate(steps):
        _current.begin(number)
        if step.group == "ledger" and collect_failed:
            results.append(StepResult(step.name, "skipped", 0.0, "a collection step failed"))
            report(f"[{step.name}] skipped: a collection step failed")
            continue
        started = clock()
        try:
            step.run()
        except SystemExit as error:
            if error.code in (0, None):
                _current.end_step()
                results.append(StepResult(step.name, "ok", clock() - started))
                report(f"[{step.name}] ok")
                continue
            detail = _failure_text(error)
        except Exception as error:  # noqa: BLE001 - one step's failure must not stop the others
            detail = _failure_text(error)
        else:
            _current.end_step()
            results.append(StepResult(step.name, "ok", clock() - started))
            report(f"[{step.name}] ok")
            continue
        _current.end_step()
        collect_failed = collect_failed or step.group == "collect"
        results.append(StepResult(step.name, "failed", clock() - started, detail))
        report(f"[{step.name}] FAILED: {detail}")
    return results


def summary(results: Sequence[StepResult]) -> str:
    def names(status: str) -> str:
        found = [r.name for r in results if r.status == status]
        return f" ({', '.join(found)})" if found else ""

    count = {s: sum(r.status == s for r in results) for s in ("ok", "failed", "skipped")}
    return (
        f"update: {count['ok']} ok, {count['failed']} failed{names('failed')}, "
        f"{count['skipped']} skipped{names('skipped')}"
    )


class AlreadyRunning(RuntimeError):
    pass


class UpdateLock:
    """A pid lock file so two runs never overlap (a run can outlast a day on a slow quota)."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @staticmethod
    def _alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def __enter__(self) -> UpdateLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    pid = int(self.path.read_text().strip())
                except (OSError, ValueError):
                    pid = 0
                if pid and self._alive(pid):
                    raise AlreadyRunning(f"another update is running (pid {pid})") from None
                self.path.unlink(missing_ok=True)  # stale lock from a crashed run
                continue
            with os.fdopen(descriptor, "w") as handle:
                handle.write(str(os.getpid()))
            return self
        raise AlreadyRunning("could not take the update lock")

    def __exit__(self, *_: object) -> None:
        self.path.unlink(missing_ok=True)


def load_env_file(path: Path, environ: MutableMapping[str, str] | None = None) -> list[str]:
    """Set variables from a KEY=VALUE file without overriding existing ones.

    Returns the names that were set, never the values. Blank lines, `#` comments, an optional
    `export ` prefix and one pair of surrounding quotes are handled; empty values are ignored.
    """
    target = os.environ if environ is None else environ
    if not path.is_file():
        return []
    applied = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        name, _, value = text.removeprefix("export ").partition("=")
        name, value = name.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if name and value and not target.get(name):
            target[name] = value
            applied.append(name)
    return applied


def notify_failure(
    failed: Sequence[str],
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    platform: str = sys.platform,
) -> None:
    """A macOS notification naming the failed steps (step names only, no details)."""
    if platform != "darwin" or not failed:
        return
    text = "Asset Frame 갱신 실패: " + ", ".join(failed)
    script = f'display notification "{text}" with title "Asset Frame"'
    with contextlib.suppress(OSError, subprocess.TimeoutExpired):
        run(["/usr/bin/osascript", "-e", script], capture_output=True, timeout=10, check=False)

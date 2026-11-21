import plistlib
import subprocess
from pathlib import Path

import pytest

from asset_frame import schedule
from asset_frame.schedule import LABEL, ScheduleError, build_plist


class Launchctl:
    def __init__(self, stdout: str = "", returncode: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.stdout, self.returncode = stdout, returncode

    def __call__(self, argv, **_):  # type: ignore[no-untyped-def]
        self.calls.append(argv)
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, "denied")


def test_plist_runs_the_update_daily_from_the_repository_without_any_secret(tmp_path: Path) -> None:
    data = plistlib.loads(build_plist(python="/py/bin/python", root=tmp_path, hour=7, minute=30))
    assert data["Label"] == LABEL
    assert data["ProgramArguments"] == ["/py/bin/python", "-m", "asset_frame", "update"]
    assert data["WorkingDirectory"] == str(tmp_path)
    assert data["StartCalendarInterval"] == {"Hour": 7, "Minute": 30}
    assert data["RunAtLoad"] is False
    assert data["StandardOutPath"] == str(tmp_path / "var/logs/update.log")
    assert "API_KEY" not in str(data)


@pytest.mark.parametrize("hour, minute", [(24, 0), (-1, 0), (7, 60)])
def test_an_impossible_time_is_rejected(tmp_path: Path, hour: int, minute: int) -> None:
    with pytest.raises(ScheduleError):
        build_plist(python="p", root=tmp_path, hour=hour, minute=minute)


def test_install_writes_the_plist_then_reloads_it(tmp_path: Path) -> None:
    run = Launchctl()
    path = schedule.install(tmp_path / "repo", 7, 30, python="/py", home=tmp_path, run=run)
    assert path == tmp_path / "Library/LaunchAgents" / f"{LABEL}.plist" and path.exists()
    assert (tmp_path / "repo/var/logs").is_dir()
    assert [c[1] for c in run.calls] == ["bootout", "bootstrap"]  # replace an older registration
    assert run.calls[1][-1] == str(path)


def test_a_failed_bootstrap_is_reported(tmp_path: Path) -> None:
    with pytest.raises(ScheduleError, match="bootstrap failed"):
        schedule.install(
            tmp_path / "r", 7, 30, python="/py", home=tmp_path, run=Launchctl(returncode=5)
        )


def test_uninstall_removes_the_file_and_says_whether_it_existed(tmp_path: Path) -> None:
    run = Launchctl()
    assert schedule.uninstall(home=tmp_path, run=run) is False
    schedule.install(tmp_path / "r", 7, 30, python="/py", home=tmp_path, run=Launchctl())
    assert schedule.uninstall(home=tmp_path, run=run) is True
    assert not schedule.plist_path(tmp_path).exists()


def test_status_reports_the_schedule_and_the_last_exit_code(tmp_path: Path) -> None:
    schedule.install(tmp_path / "r", 7, 30, python="/py", home=tmp_path, run=Launchctl())
    info = schedule.status(home=tmp_path, run=Launchctl(stdout="x\n\tlast exit code = 0\n"))
    assert info["installed"] and info["loaded"] and info["schedule"] == "07:30 daily"
    assert info["last_exit"] == "0"
    gone = schedule.status(home=tmp_path / "none", run=Launchctl(returncode=113))
    assert gone["installed"] is False and gone["loaded"] is False

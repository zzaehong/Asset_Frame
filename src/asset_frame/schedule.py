"""Register the daily `asset-frame update` with macOS launchd (ADR-0012).

A LaunchAgent starts the job at the set time every day; if the Mac is asleep it runs once on wake.
The plist holds no secret: keys come from `.env` (loaded by `update`) or the Keychain.
"""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

LABEL = "local.assetframe.update"
LOG_RELATIVE = Path("var/logs/update.log")
Run = Callable[..., subprocess.CompletedProcess[str]]


class ScheduleError(RuntimeError):
    pass


def plist_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / "Library/LaunchAgents" / f"{LABEL}.plist"


def build_plist(*, python: str, root: Path, hour: int, minute: int) -> bytes:
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ScheduleError("hour must be 0-23 and minute 0-59")
    log = str(root / LOG_RELATIVE)
    return plistlib.dumps(
        {
            "Label": LABEL,
            "ProgramArguments": [python, "-m", "asset_frame", "update"],
            "WorkingDirectory": str(root),
            "StartCalendarInterval": {"Hour": hour, "Minute": minute},
            "RunAtLoad": False,
            "StandardOutPath": log,
            "StandardErrorPath": log,
            "ProcessType": "Background",
            "EnvironmentVariables": {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
        }
    )


def _domain() -> str:
    return f"gui/{os.getuid()}"


def install(
    root: Path,
    hour: int,
    minute: int,
    *,
    python: str = sys.executable,
    home: Path | None = None,
    run: Run = subprocess.run,
) -> Path:
    path = plist_path(home)
    payload = build_plist(python=python, root=root, hour=hour, minute=minute)
    path.parent.mkdir(parents=True, exist_ok=True)
    (root / LOG_RELATIVE).parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    run(
        ["launchctl", "bootout", f"{_domain()}/{LABEL}"],
        capture_output=True,
        text=True,
        check=False,
    )
    result = run(
        ["launchctl", "bootstrap", _domain(), str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ScheduleError(
            f"launchctl bootstrap failed: {result.stderr.strip() or result.returncode}"
        )
    return path


def uninstall(*, home: Path | None = None, run: Run = subprocess.run) -> bool:
    """Unload and delete the agent; False if it was not installed."""
    path = plist_path(home)
    existed = path.exists()
    run(
        ["launchctl", "bootout", f"{_domain()}/{LABEL}"],
        capture_output=True,
        text=True,
        check=False,
    )
    path.unlink(missing_ok=True)
    return existed


def status(*, home: Path | None = None, run: Run = subprocess.run) -> dict:
    path = plist_path(home)
    info: dict = {"installed": path.exists(), "loaded": False, "schedule": None, "last_exit": None}
    if info["installed"]:
        plist = plistlib.loads(path.read_bytes())
        interval = plist.get("StartCalendarInterval", {})
        info["schedule"] = f"{interval.get('Hour', 0):02d}:{interval.get('Minute', 0):02d} daily"
        info["log"] = plist.get("StandardOutPath")
    result = run(
        ["launchctl", "print", f"{_domain()}/{LABEL}"], capture_output=True, text=True, check=False
    )
    if result.returncode == 0:
        info["loaded"] = True
        for line in result.stdout.splitlines():
            if "last exit code" in line:
                info["last_exit"] = line.split("=", 1)[1].strip()
    return info

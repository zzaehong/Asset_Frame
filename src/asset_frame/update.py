"""One command that refreshes everything for a scheduled run (ADR-0012).

Steps run in order; a failed step does not stop the rest, and the ledger step is skipped when any
collection step failed (a permanent record must not be built from stale data). `.env` values fill
in only variables that are not already set, and nothing here prints a value.
"""

from __future__ import annotations

import contextlib
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


def run_steps(
    steps: Sequence[Step],
    *,
    report: Callable[[str], None] = print,
    clock: Callable[[], float] = time.monotonic,
) -> list[StepResult]:
    results: list[StepResult] = []
    collect_failed = False
    for step in steps:
        if step.group == "ledger" and collect_failed:
            results.append(StepResult(step.name, "skipped", 0.0, "a collection step failed"))
            report(f"[{step.name}] skipped: a collection step failed")
            continue
        started = clock()
        try:
            step.run()
        except SystemExit as error:
            if error.code in (0, None):
                results.append(StepResult(step.name, "ok", clock() - started))
                report(f"[{step.name}] ok")
                continue
            detail = _failure_text(error)
        except Exception as error:  # noqa: BLE001 - one step's failure must not stop the others
            detail = _failure_text(error)
        else:
            results.append(StepResult(step.name, "ok", clock() - started))
            report(f"[{step.name}] ok")
            continue
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

"""API key lookup: the environment variable first, then the macOS Keychain (ADR-0011).

The Mac app stores keys in the Keychain under KEYCHAIN_SERVICE (account = variable name). A value
is never printed, logged or passed on a command line: the Keychain is read with `security ... -w`,
which writes the value to stdout only. Where the Keychain is unavailable (Linux, WSL) only the
environment variable is used.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Mapping

KEYCHAIN_SERVICE = "local.assetframe.api-keys"
SECURITY_TOOL = "/usr/bin/security"
KEYCHAIN_TIMEOUT_SECONDS = 60  # the first read can wait for the user to click "Always Allow"


def keychain_lookup(
    name: str,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    platform: str = sys.platform,
) -> str | None:
    """The stored value for `name`, or None (not found, denied, timed out, not macOS)."""
    if platform != "darwin":
        return None
    try:
        result = run(
            [SECURITY_TOOL, "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", name, "-w"],
            capture_output=True,
            text=True,
            timeout=KEYCHAIN_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() or None if result.returncode == 0 else None


def resolve_secret(name: str, environ: Mapping[str, str] | None = None) -> str | None:
    """Environment variable if set and non-empty, else the Keychain value, else None."""
    value = (os.environ if environ is None else environ).get(name)
    return value or keychain_lookup(name)

import subprocess

import pytest

from asset_frame import secrets
from asset_frame.cli import _required_environment
from asset_frame.secrets import KEYCHAIN_SERVICE, keychain_lookup, resolve_secret


class Recorder:
    def __init__(self, returncode: int = 0, stdout: str = "", error: Exception | None = None):
        self.returncode, self.stdout, self.error = returncode, stdout, error
        self.calls: list[list[str]] = []

    def __call__(self, argv, **_):  # type: ignore[no-untyped-def]
        self.calls.append(argv)
        if self.error:
            raise self.error
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, "")


def test_keychain_lookup_reads_the_item_and_never_puts_a_value_on_the_command_line() -> None:
    run = Recorder(stdout="  s3cret-value \n")
    assert keychain_lookup("TIINGO_API_KEY", run=run, platform="darwin") == "s3cret-value"
    assert run.calls == [
        [
            "/usr/bin/security",
            "find-generic-password",
            "-s",
            KEYCHAIN_SERVICE,
            "-a",
            "TIINGO_API_KEY",
            "-w",
        ]
    ]
    assert "s3cret-value" not in " ".join(run.calls[0])


@pytest.mark.parametrize(
    "run",
    [
        Recorder(returncode=44),  # item not found
        Recorder(returncode=0, stdout="\n"),  # empty value
        Recorder(error=OSError("no security tool")),
        Recorder(error=subprocess.TimeoutExpired("security", 60)),  # nobody clicked "allow"
    ],
)
def test_keychain_lookup_failures_give_none(run: Recorder) -> None:
    assert keychain_lookup("FRED_API_KEY", run=run, platform="darwin") is None


def test_keychain_is_not_touched_off_macos() -> None:
    run = Recorder(stdout="value")
    assert keychain_lookup("FRED_API_KEY", run=run, platform="linux") is None
    assert run.calls == []


def test_environment_wins_and_an_empty_variable_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[str] = []
    monkeypatch.setattr(
        secrets, "keychain_lookup", lambda name: asked.append(name) or "from-keychain"
    )
    assert resolve_secret("K", {"K": "from-env"}) == "from-env" and asked == []
    assert resolve_secret("K", {"K": ""}) == "from-keychain"
    assert resolve_secret("K", {}) == "from-keychain"


def test_required_environment_uses_the_keychain_and_never_echoes_a_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
    monkeypatch.setattr(secrets, "keychain_lookup", lambda name: "kc-value")
    assert _required_environment("TIINGO_API_KEY") == "kc-value"
    monkeypatch.setattr(secrets, "keychain_lookup", lambda name: None)
    with pytest.raises(SystemExit) as error:
        _required_environment("TIINGO_API_KEY")
    message = str(error.value)
    assert "TIINGO_API_KEY" in message and "Keychain" in message and "kc-value" not in message

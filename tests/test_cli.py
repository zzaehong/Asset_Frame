import pytest

from asset_frame.cli import _required_environment


def test_required_environment_rejects_missing_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MISSING_TEST_VALUE", raising=False)

    with pytest.raises(SystemExit):
        _required_environment("MISSING_TEST_VALUE")

import pytest


@pytest.fixture(autouse=True)
def no_real_keychain(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never read the developer's Keychain, so a stored key cannot change their outcome."""
    monkeypatch.setattr("asset_frame.secrets.keychain_lookup", lambda name: None)

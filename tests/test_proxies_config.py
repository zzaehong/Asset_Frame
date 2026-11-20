from datetime import date
from pathlib import Path

import pytest

from asset_frame.proxies import ProxyConfigError, load_proxies, proxy_universe
from asset_frame.universe import load_universe

UNIVERSE = load_universe(Path("config/universe.toml"))


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "proxies.toml"
    path.write_text("schema_version = 1\n" + body)
    return path


ENTRY = (
    'target = "{t}"\nproxy = "{p}"\nname = "n"\nexpected_inception = "1990-01"\nfidelity = "{f}"\n'
)


def test_repository_config_loads_and_every_target_is_in_the_universe() -> None:
    specs = load_proxies(Path("config/proxies.toml"), UNIVERSE)

    assert {s.target for s in specs} >= {"SPY", "TLT", "IEF", "GLD"}
    assert next(s for s in specs if s.target == "GLD").fidelity == "rough"
    assert next(s for s in specs if s.target == "SPY").expected_inception == date(1976, 8, 1)


def test_shared_proxy_funds_are_collected_once() -> None:
    specs = load_proxies(Path("config/proxies.toml"), UNIVERSE)

    funds = [asset.ticker for asset in proxy_universe(specs)]

    assert len(funds) == len(set(funds)) and "VWEHX" in funds and "VWESX" in funds


@pytest.mark.parametrize(
    "body",
    [
        "[[proxies]]\n" + ENTRY.format(t="NOPE", p="VFINX", f="index"),
        "[[proxies]]\n" + ENTRY.format(t="SPY", p="VFINX", f="great"),
        "[[proxies]]\n" + ENTRY.format(t="SPY", p="TLT", f="index"),
        "[[proxies]]\n"
        + ENTRY.format(t="SPY", p="VFINX", f="index")
        + "[[proxies]]\n"
        + ENTRY.format(t="SPY", p="VFIAX", f="index"),
    ],
)
def test_invalid_configs_are_rejected(tmp_path: Path, body: str) -> None:
    with pytest.raises(ProxyConfigError):
        load_proxies(write(tmp_path, body), UNIVERSE)

"""Load config/proxies.toml: older funds whose returns stand in for a young ETF's missing months."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from asset_frame.returns.proxy import MIN_CORRELATION
from asset_frame.universe import UniverseAsset


class ProxyConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ProxySpec:
    target: str
    proxy: str
    name: str
    expected_inception: date
    fidelity: str


def load_proxies(path: Path, universe: tuple[UniverseAsset, ...]) -> tuple[ProxySpec, ...]:
    with path.open("rb") as config_file:
        payload = tomllib.load(config_file)
    if payload.get("schema_version") != 1:
        raise ProxyConfigError("unsupported proxy schema version")
    tickers = {asset.ticker for asset in universe}
    specs = []
    for item in payload.get("proxies", []):
        try:
            text = str(item["expected_inception"])
            spec = ProxySpec(
                target=str(item["target"]),
                proxy=str(item["proxy"]),
                name=str(item["name"]),
                expected_inception=date.fromisoformat(text + "-01" if len(text) == 7 else text),
                fidelity=str(item["fidelity"]),
            )
        except (KeyError, ValueError) as error:
            raise ProxyConfigError(f"invalid proxy entry: {error}") from error
        if spec.fidelity not in MIN_CORRELATION:
            raise ProxyConfigError(f"{spec.target}: unknown fidelity {spec.fidelity}")
        if spec.target not in tickers:
            raise ProxyConfigError(f"{spec.target}: target is not in the universe")
        if spec.proxy in tickers:
            raise ProxyConfigError(f"{spec.proxy}: a universe asset cannot be a proxy")
        specs.append(spec)
    targets = [spec.target for spec in specs]
    if len(targets) != len(set(targets)):
        raise ProxyConfigError("each target may have one proxy")
    return tuple(specs)


def proxy_universe(specs: tuple[ProxySpec, ...]) -> tuple[UniverseAsset, ...]:
    """One collection entry per distinct proxy fund (several targets may share one)."""
    seen: dict[str, ProxySpec] = {}
    for spec in specs:
        seen.setdefault(spec.proxy, spec)
    return tuple(
        UniverseAsset(
            ticker=spec.proxy,
            name=spec.name,
            level=1,
            group="proxy",
            role="granular",
            refines=None,
            expected_inception=spec.expected_inception,
            verified_inception=None,
        )
        for spec in seen.values()
    )

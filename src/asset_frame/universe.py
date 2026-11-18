from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

INCEPTION_TOLERANCE_DAYS = 31
MULTI_ANCHOR_GROUPS = {"gics_sector": 9}


class UniverseConfigError(ValueError):
    """Raised when the universe configuration violates its structural rules."""


@dataclass(frozen=True, slots=True)
class UniverseAsset:
    ticker: str
    name: str
    level: int
    group: str
    role: str
    refines: str | None
    expected_inception: date
    verified_inception: date | None


@dataclass(frozen=True, slots=True)
class InceptionCheck:
    ticker: str
    expected: date
    provider_start: date | None
    first_price_date: date | None
    status: str


def load_universe(path: Path) -> tuple[UniverseAsset, ...]:
    with path.open("rb") as config_file:
        payload = tomllib.load(config_file)
    if payload.get("schema_version") != 1:
        raise UniverseConfigError("unsupported universe schema version")
    try:
        assets = tuple(_parse_asset(item) for item in payload.get("assets", []))
    except (KeyError, TypeError, ValueError) as error:
        raise UniverseConfigError(f"invalid universe asset: {error}") from error
    validate_universe(assets)
    return assets


def validate_universe(assets: tuple[UniverseAsset, ...]) -> None:
    tickers = [asset.ticker for asset in assets]
    if len(tickers) != len(set(tickers)):
        raise UniverseConfigError("universe tickers must be unique")
    anchors: dict[str, set[str]] = {}
    for asset in assets:
        if asset.level not in (1, 2):
            raise UniverseConfigError(f"{asset.ticker}: level must be 1 or 2")
        if asset.role not in ("anchor", "granular"):
            raise UniverseConfigError(f"{asset.ticker}: role must be anchor or granular")
        if asset.role == "anchor":
            if asset.refines is not None:
                raise UniverseConfigError(f"{asset.ticker}: an anchor must not refine another")
            anchors.setdefault(asset.group, set()).add(asset.ticker)
    for group in {asset.group for asset in assets}:
        expected = MULTI_ANCHOR_GROUPS.get(group, 1)
        if len(anchors.get(group, ())) != expected:
            raise UniverseConfigError(f"group {group} must have exactly {expected} anchor(s)")
    for asset in assets:
        if asset.role == "granular" and asset.refines not in anchors.get(asset.group, ()):
            raise UniverseConfigError(
                f"{asset.ticker}: refines must name an anchor in group {asset.group}"
            )


def compare_inception(
    ticker: str,
    expected: date,
    provider_start: date | None,
    first_price_date: date | None,
) -> InceptionCheck:
    """ok only when both provider metadata and collected prices sit within tolerance."""
    within = all(
        value is not None and abs((value - expected).days) <= INCEPTION_TOLERANCE_DAYS
        for value in (provider_start, first_price_date)
    )
    return InceptionCheck(
        ticker, expected, provider_start, first_price_date, "ok" if within else "mismatch"
    )


def parse_provider_start(metadata_body: bytes) -> date | None:
    value = json.loads(metadata_body).get("startDate")
    return date.fromisoformat(value[:10]) if value else None


def record_verified_inception(path: Path, ticker: str, verified: date) -> None:
    """Rewrite only the verified_inception line inside this ticker's [[assets]] block."""
    text = path.read_text()
    blocks = text.split("[[assets]]")
    for index, block in enumerate(blocks):
        if re.search(rf'^ticker = "{re.escape(ticker)}"$', block, re.MULTILINE):
            blocks[index], count = re.subn(
                r'^verified_inception = ".*"$',
                f'verified_inception = "{verified.isoformat()}"',
                block,
                count=1,
                flags=re.MULTILINE,
            )
            if count != 1:
                raise UniverseConfigError(f"{ticker}: verified_inception line not found")
            path.write_text("[[assets]]".join(blocks))
            return
    raise UniverseConfigError(f"{ticker} is not in the universe")


def _parse_asset(item: dict[str, object]) -> UniverseAsset:
    expected = str(item["expected_inception"])
    verified = str(item["verified_inception"])
    return UniverseAsset(
        ticker=str(item["ticker"]),
        name=str(item["name"]),
        level=int(item["level"]),  # type: ignore[call-overload]
        group=str(item["group"]),
        role=str(item["role"]),
        refines=str(item["refines"]) or None,
        expected_inception=date.fromisoformat(f"{expected}-01"),
        verified_inception=date.fromisoformat(verified) if verified else None,
    )

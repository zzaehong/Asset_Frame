"""The individual-stock watchlist (ADR-0010): which tickers to collect, chosen by the user.

config/stock_candidates.toml lists suggestions (major holdings of the tracked ETFs); the user picks
tickers in the dashboard, which produces config/stocks.toml. Only tickers in stocks.toml are
collected. The ETF universe, strategies and ledger never read these stocks.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from asset_frame.ingestion.universe_service import LOOKBACK_DAYS, collection_windows
from asset_frame.universe import UniverseAsset

LIMIT = 50  # Tiingo Starter: 500 unique symbols a month, 50 requests an hour (ADR-0010)
HISTORY_START = date(2010, 1, 1)
REQUEST_INTERVAL_SECONDS = 75
TICKER = re.compile(r"^[A-Z]{1,5}(-[A-Z])?$")  # US tickers; class shares in Tiingo form (BRK-B)


class StockConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class StockSpec:
    ticker: str
    name: str


@dataclass(frozen=True, slots=True)
class Candidate:
    ticker: str
    name: str
    gics_sector: str
    etfs: tuple[str, ...]


def load_candidates(path: Path) -> tuple[Candidate, ...]:
    with path.open("rb") as config_file:
        items = tomllib.load(config_file).get("candidates", [])
    return tuple(
        Candidate(c["ticker"], c["name"], c["gics_sector"], tuple(c["etfs"])) for c in items
    )


def load_stocks(
    path: Path, universe: tuple[UniverseAsset, ...], candidates: tuple[Candidate, ...] = ()
) -> tuple[StockSpec, ...]:
    """The selected stocks; a missing file means nothing is selected."""
    if not path.exists():
        return ()
    with path.open("rb") as config_file:
        payload = tomllib.load(config_file)
    if payload.get("schema_version") != 1:
        raise StockConfigError("unsupported stocks schema version")
    names = {c.ticker: c.name for c in candidates}
    etfs = {asset.ticker for asset in universe}
    specs: list[StockSpec] = []
    for item in payload.get("stocks", []):
        ticker = str(item.get("ticker", "")).strip().upper()
        if not TICKER.match(ticker):
            raise StockConfigError(f"invalid ticker: {ticker!r}")
        if ticker in etfs:
            raise StockConfigError(f"{ticker}: is an ETF already in the universe")
        specs.append(StockSpec(ticker, str(item.get("name") or names.get(ticker) or ticker)))
    tickers = [spec.ticker for spec in specs]
    if len(tickers) != len(set(tickers)):
        raise StockConfigError("duplicate tickers in stocks.toml")
    if len(tickers) > LIMIT:
        raise StockConfigError(f"{len(tickers)} stocks selected; the limit is {LIMIT}")
    return tuple(specs)


def stock_universe(specs: tuple[StockSpec, ...]) -> tuple[UniverseAsset, ...]:
    """Collection entries; the first fetch starts at HISTORY_START."""
    return tuple(
        UniverseAsset(
            ticker=spec.ticker,
            name=spec.name,
            level=3,
            group="stock",
            role="watchlist",
            refines=None,
            expected_inception=HISTORY_START + timedelta(days=LOOKBACK_DAYS),
            verified_inception=None,
        )
        for spec in specs
    )


def stock_summary(
    specs: tuple[StockSpec, ...],
    candidates: tuple[Candidate, ...],
    last_price_date: Callable[[str], date | None],
    today: date,
) -> dict:
    """Dashboard payload: candidates (plus hand-added selections), the current selection, cost."""
    rows = [
        {"ticker": c.ticker, "name": c.name, "sector": c.gics_sector, "etfs": list(c.etfs)}
        for c in candidates
    ]
    known = {row["ticker"] for row in rows}
    rows += [
        {"ticker": s.ticker, "name": s.name, "sector": "직접 추가", "etfs": []}
        for s in specs
        if s.ticker not in known
    ]
    for row in rows:
        last = last_price_date(row["ticker"])
        row["collected_through"] = None if last is None else last.isoformat()
    requests = len(collection_windows(HISTORY_START, today))
    return {
        "limit": LIMIT,
        "history_start": HISTORY_START.isoformat(),
        "seconds_per_ticker": requests * REQUEST_INTERVAL_SECONDS,
        "selected": [spec.ticker for spec in specs],
        "candidates": rows,
    }

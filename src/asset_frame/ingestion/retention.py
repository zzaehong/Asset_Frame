from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    news_lookback_days: int
    news_max_articles_per_asset: int
    news_max_records_per_request: int
    filing_lookback_years: int
    filing_max_documents_per_asset_source: int
    fact_lookback_years: int
    fact_max_per_asset_source: int
    price_lookback_years: int
    price_max_observations_per_asset_source: int
    require_complete_ohlc: bool
    raw_unreferenced_lookback_days: int


def load_retention_policy(path: Path) -> RetentionPolicy:
    with path.open("rb") as file:
        payload = tomllib.load(file)
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported retention policy schema version")
    news = _table(payload, "news")
    filings = _table(payload, "filings")
    facts = _table(payload, "financial_facts")
    prices = _table(payload, "prices")
    raw = _table(payload, "raw_snapshots")
    require_ohlc = prices.get("require_complete_ohlc")
    if require_ohlc is not True:
        raise ValueError("retention policy must require complete OHLC prices")
    return RetentionPolicy(
        news_lookback_days=_positive(news, "lookback_days"),
        news_max_articles_per_asset=_positive(news, "max_articles_per_asset"),
        news_max_records_per_request=_positive(news, "max_records_per_request"),
        filing_lookback_years=_positive(filings, "lookback_years"),
        filing_max_documents_per_asset_source=_positive(filings, "max_documents_per_asset_source"),
        fact_lookback_years=_positive(facts, "lookback_years"),
        fact_max_per_asset_source=_positive(facts, "max_facts_per_asset_source"),
        price_lookback_years=_positive(prices, "lookback_years"),
        price_max_observations_per_asset_source=_positive(
            prices, "max_observations_per_asset_source"
        ),
        require_complete_ohlc=require_ohlc,
        raw_unreferenced_lookback_days=_positive(raw, "unreferenced_lookback_days"),
    )


def years_before(as_of_date: date, years: int) -> date:
    if years <= 0:
        raise ValueError("lookback years must be positive")
    try:
        return as_of_date.replace(year=as_of_date.year - years)
    except ValueError:
        return as_of_date.replace(year=as_of_date.year - years, day=28)


def _table(payload: dict[str, object], name: str) -> dict[str, object]:
    value = payload.get(name)
    if not isinstance(value, dict):
        raise ValueError(f"retention policy section is required: {name}")
    return value


def _positive(table: dict[str, object], name: str) -> int:
    value = table.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"retention policy value must be positive: {name}")
    return value

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta

from asset_frame.domain.models import AssetType
from asset_frame.ingestion.tiingo_service import TiingoEodCollector
from asset_frame.storage.research import ResearchStore
from asset_frame.universe import UniverseAsset

WINDOW_YEARS = 10
# Consecutive windows share these days so every daily return can be measured in one snapshot.
WINDOW_OVERLAP_DAYS = 10
# Ask for a year before the expected inception so an earlier real start is not cut off.
LOOKBACK_DAYS = 365


@dataclass(slots=True)
class UniverseIngestResult:
    collected: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)


def collection_windows(start: date, end: date) -> tuple[tuple[date, date], ...]:
    """Split [start, end] into overlapping windows that fit the connector's 10-year limit."""
    if start > end:
        raise ValueError("collection start must not be after end")
    windows = []
    window_start = start
    while True:
        window_end = min(end, _add_years(window_start, WINDOW_YEARS) - timedelta(days=1))
        windows.append((window_start, window_end))
        if window_end == end:
            return tuple(windows)
        window_start = window_end - timedelta(days=WINDOW_OVERLAP_DAYS)


def ingest_universe(
    assets: tuple[UniverseAsset, ...],
    *,
    collector: TiingoEodCollector,
    store: ResearchStore,
    api_key: str,
    end_date: date,
    report: Callable[[str], None] = print,
) -> UniverseIngestResult:
    """Collect every ticker's full history; a ticker done for end_date is skipped on rerun."""
    result = UniverseIngestResult()
    for asset in assets:
        if store.is_ingest_complete(asset.ticker, end_date):
            result.skipped.append(asset.ticker)
            continue
        start = asset.expected_inception - timedelta(days=LOOKBACK_DAYS)
        try:
            for window_start, window_end in collection_windows(start, end_date):
                collector.collect(
                    ticker=asset.ticker,
                    asset_type=AssetType.ETF,
                    api_key=api_key,
                    start_date=window_start,
                    end_date=window_end,
                )
        except Exception as error:  # noqa: BLE001 - one ticker's failure must not stop the rest
            result.failed[asset.ticker] = f"{type(error).__name__}: {error}"
            report(f"{asset.ticker}: failed ({result.failed[asset.ticker]})")
            continue
        store.mark_ingest_complete(asset.ticker, end_date)
        result.collected.append(asset.ticker)
        report(f"{asset.ticker}: collected")
    return result


def _add_years(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:
        return day.replace(year=day.year + years, day=28)

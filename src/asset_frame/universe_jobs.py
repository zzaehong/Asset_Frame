"""Glue between the universe config, SQLite and the raw store for the universe CLI commands."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from asset_frame.connectors.tiingo import TIINGO_SOURCE_ID, build_metadata_request, tiingo_asset_id
from asset_frame.returns.series import (
    CALC_VERSION,
    UniverseReturns,
    compute_universe_returns,
)
from asset_frame.storage.research import ResearchStore
from asset_frame.universe import (
    InceptionCheck,
    UniverseAsset,
    compare_inception,
    parse_provider_start,
    record_verified_inception,
)

CALENDAR_TICKER = "SPY"
CASH_GROUP = "cash"
CASH_PROXY_SERIES = "DTB3"


@dataclass(frozen=True, slots=True)
class StatusRow:
    ticker: str
    level: int
    group: str
    role: str
    verified_inception: date | None
    first_month: date | None
    last_month: date | None
    missing_trading_days: int
    anomalies: int
    proxy_months: int


def verify_universe(
    assets: tuple[UniverseAsset, ...],
    *,
    store: ResearchStore,
    raw_root: Path,
    config_path: Path,
) -> tuple[InceptionCheck, ...]:
    """Compare inception dates; write verified_inception to the config only for `ok`."""
    checks = []
    for asset in assets:
        # The metadata URL carries no secret, so the stored (masked) URL equals the built one.
        metadata_url = build_metadata_request(asset.ticker, api_key="unused").url
        path = store.latest_raw_snapshot_path(source_id=TIINGO_SOURCE_ID, request_url=metadata_url)
        provider_start = parse_provider_start((raw_root / path).read_bytes()) if path else None
        points = store.price_points(tiingo_asset_id(asset.ticker))
        first_price = points[0].trading_date if points else None
        check = compare_inception(
            asset.ticker, asset.expected_inception, provider_start, first_price
        )
        if check.status == "ok" and provider_start is not None:
            record_verified_inception(config_path, asset.ticker, provider_start)
        checks.append(check)
    store.save_verification(checks)
    return tuple(checks)


def build_returns(
    assets: tuple[UniverseAsset, ...], *, store: ResearchStore
) -> tuple[UniverseReturns, str]:
    cash_ticker = next(asset.ticker for asset in assets if asset.group == CASH_GROUP)
    result = compute_universe_returns(
        {asset.ticker: store.price_points(tiingo_asset_id(asset.ticker)) for asset in assets},
        calendar_ticker=CALENDAR_TICKER,
        cash_ticker=cash_ticker,
        cash_proxy=store.macro_points(CASH_PROXY_SERIES),
    )
    computed_at = store.save_build(result.returns, result.anomalies, calc_version=CALC_VERSION)
    return result, computed_at


def universe_status(
    assets: tuple[UniverseAsset, ...], *, store: ResearchStore
) -> tuple[StatusRow, ...]:
    months, anomaly_counts = store.latest_build()
    calendar = sorted(
        {point.trading_date for point in store.price_points(tiingo_asset_id(CALENDAR_TICKER))}
    )
    rows = []
    for asset in assets:
        dates = {point.trading_date for point in store.price_points(tiingo_asset_id(asset.ticker))}
        missing = (
            sum(1 for day in calendar if day >= min(dates) and day not in dates) if dates else 0
        )
        ticker_months = months.get(asset.ticker, [])
        rows.append(
            StatusRow(
                ticker=asset.ticker,
                level=asset.level,
                group=asset.group,
                role=asset.role,
                verified_inception=asset.verified_inception,
                first_month=ticker_months[0][0] if ticker_months else None,
                last_month=ticker_months[-1][0] if ticker_months else None,
                missing_trading_days=missing,
                anomalies=anomaly_counts.get(asset.ticker, 0),
                proxy_months=sum(1 for _, is_proxy in ticker_months if is_proxy),
            )
        )
    return tuple(rows)

"""Glue: build proxy-extended monthly returns from stored fund prices and the latest ETF build."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from asset_frame.connectors.tiingo import tiingo_asset_id
from asset_frame.proxies import ProxySpec
from asset_frame.returns.proxy import (
    CALC_VERSION,
    ProxyDecision,
    as_floats,
    decide,
    decimal_returns,
    overlap_stats,
    splice_levels,
    splice_proxy,
)
from asset_frame.returns.series import (
    MonthlyReturn,
    UnlinkedPriceError,
    month_ends,
    monthly_returns,
    total_return_index,
)
from asset_frame.storage.research import ProxyCheckRow, ResearchStore


def build_proxy_returns(
    specs: tuple[ProxySpec, ...], *, store: ResearchStore, calendar_ticker: str = "SPY"
) -> tuple[dict[str, tuple[MonthlyReturn, ...]], tuple[ProxyCheckRow, ...], str]:
    """Spliced stand-in months for each target whose proxy passes its fidelity check.

    Month ends come from the union of the calendar ETF's and the proxies' trading days (the last
    trading day of each month, excluding the latest month), the same rule the ETF build uses.
    """
    etf_returns = store.latest_returns()
    indexes = {}
    problems: dict[str, str] = {}
    for ticker in {spec.proxy for spec in specs}:
        points = store.price_points(tiingo_asset_id(ticker))
        if not points:
            problems[ticker] = "no prices: run `asset-frame ingest-proxies`"
            continue
        try:
            indexes[ticker] = total_return_index(points)
        except UnlinkedPriceError as error:
            problems[ticker] = str(error)
    calendar = {p.trading_date for p in store.price_points(tiingo_asset_id(calendar_ticker))}
    for index in indexes.values():
        calendar |= {point.trading_date for point in index}
    ends = month_ends(calendar)
    proxy_months = {ticker: monthly_returns(index, ends) for ticker, index in indexes.items()}

    returns: dict[str, tuple[MonthlyReturn, ...]] = {}
    checks: list[ProxyCheckRow] = []
    for spec in specs:
        target = etf_returns.get(spec.target, {})
        if spec.proxy in problems or not target:
            reason = problems.get(spec.proxy, "target has no ETF returns: run `build-returns`")
            checks.append(
                ProxyCheckRow(
                    spec.target, spec.proxy, spec.fidelity, 0, None, None, None, False, reason
                )
            )
            continue
        proxy = proxy_months[spec.proxy]
        stats = overlap_stats(decimal_returns(target), as_floats(proxy))
        decision: ProxyDecision = decide(stats, spec.fidelity)
        checks.append(
            ProxyCheckRow(
                spec.target,
                spec.proxy,
                spec.fidelity,
                0 if stats is None else stats.months,
                None if stats is None else stats.correlation,
                None if stats is None else stats.annual_tracking_difference,
                None if stats is None else stats.mean_abs_difference,
                decision.used,
                decision.reason,
            )
        )
        if decision.used:
            returns[spec.target] = splice_proxy(target.keys(), proxy, spec.proxy)
    return returns, tuple(checks), CALC_VERSION


def merged_returns(store: ResearchStore) -> dict[str, dict[date, Decimal]]:
    """Real ETF months plus the proxy months of the latest proxy build (earlier months only)."""
    merged = {ticker: dict(months) for ticker, months in store.latest_returns().items()}
    for ticker, months in store.latest_proxy_returns().items():
        merged.setdefault(ticker, {}).update(
            {month: value for month, value in months.items() if month not in merged.get(ticker, {})}
        )
    return merged


def spliced_levels(
    specs: tuple[ProxySpec, ...], *, store: ResearchStore, ticker: str
) -> list[tuple[date, float]]:
    """Daily total-return index of `ticker` extended backwards by its used proxy, if any."""
    own = [
        (point.trading_date, float(point.level))
        for point in total_return_index(store.price_points(tiingo_asset_id(ticker)))
    ]
    used = {row.ticker for row in store.latest_proxy_checks() if row.used}
    spec = next((s for s in specs if s.target == ticker and s.target in used), None)
    if spec is None:
        return own
    proxy = [
        (point.trading_date, float(point.level))
        for point in total_return_index(store.price_points(tiingo_asset_id(spec.proxy)))
    ]
    return splice_levels(own, proxy)

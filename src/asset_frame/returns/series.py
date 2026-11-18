"""Monthly total-return series. Pure functions: no I/O, Decimal arithmetic at fixed precision.

Concept cards: docs/concepts/total_return_index.md, monthly_return.md, cash_proxy_dtb3.md.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Context, Decimal, localcontext
from itertools import pairwise

CALC_VERSION = "monthly_return_v1"
ANOMALY_THRESHOLD = Decimal("0.25")
MINIMUM_ELIGIBLE_MONTHS = 13
_CONTEXT = Context(prec=28)


class UnlinkedPriceError(ValueError):
    """Two consecutive trading dates share no snapshot, so their return cannot be measured."""


@dataclass(frozen=True, slots=True)
class PricePoint:
    trading_date: date
    adjusted_close: Decimal
    snapshot_id: str
    fetched_at: str


@dataclass(frozen=True, slots=True)
class IndexPoint:
    trading_date: date
    level: Decimal
    daily_return: Decimal | None
    snapshot_id: str | None


@dataclass(frozen=True, slots=True)
class MacroPoint:
    observation_date: date
    value: Decimal | None
    snapshot_id: str


@dataclass(frozen=True, slots=True)
class MonthlyReturn:
    month_end: date
    total_return: Decimal
    is_proxy: bool
    source_price_version: str


def total_return_index(points: Iterable[PricePoint]) -> tuple[IndexPoint, ...]:
    """Chain-link daily adjClose ratios, each measured inside a single snapshot.

    Tiingo rescales the whole adjClose history whenever it fetches, so prices from different
    snapshots are on different scales. A daily return therefore uses the latest snapshot that
    contains both dates, and the index is the running product of those returns (start = 1).
    """
    by_date: dict[date, dict[str, PricePoint]] = {}
    for point in points:
        by_date.setdefault(point.trading_date, {})[point.snapshot_id] = point
    dates = sorted(by_date)
    if not dates:
        return ()
    index = [IndexPoint(dates[0], Decimal(1), None, None)]
    with localcontext(_CONTEXT):
        for previous, current in pairwise(dates):
            common = by_date[previous].keys() & by_date[current].keys()
            if not common:
                raise UnlinkedPriceError(f"no snapshot contains both {previous} and {current}")
            snapshot = max(common, key=lambda item: (by_date[current][item].fetched_at, item))
            daily = (
                by_date[current][snapshot].adjusted_close
                / by_date[previous][snapshot].adjusted_close
                - 1
            )
            index.append(IndexPoint(current, index[-1].level * (1 + daily), daily, snapshot))
    return tuple(index)


def return_anomalies(index: Iterable[IndexPoint]) -> tuple[IndexPoint, ...]:
    return tuple(
        point
        for point in index
        if point.daily_return is not None and abs(point.daily_return) > ANOMALY_THRESHOLD
    )


def month_ends(calendar: Iterable[date]) -> tuple[date, ...]:
    """Last calendar trading day of each month, excluding the latest (possibly partial) month."""
    last: dict[tuple[int, int], date] = {}
    for day in calendar:
        key = (day.year, day.month)
        last[key] = max(day, last.get(key, day))
    ordered = [last[key] for key in sorted(last)]
    return tuple(ordered[:-1])


def monthly_returns(
    index: Iterable[IndexPoint], calendar_month_ends: Iterable[date]
) -> tuple[MonthlyReturn, ...]:
    points = sorted(index, key=lambda point: point.trading_date)
    ends = tuple(calendar_month_ends)
    end_by_month = {(end.year, end.month): end for end in ends}
    # The asset's value for a month is its last own trading day on or before the calendar end.
    position_at: dict[date, int] = {}
    for position, point in enumerate(points):
        end = end_by_month.get((point.trading_date.year, point.trading_date.month))
        if end is not None and point.trading_date <= end:
            position_at[end] = position
    results = []
    with localcontext(_CONTEXT):
        for previous, current in pairwise(ends):
            if previous not in position_at or current not in position_at:
                continue
            start, stop = position_at[previous], position_at[current]
            value_at = {previous: points[start], current: points[stop]}
            snapshots = sorted(
                {
                    point.snapshot_id
                    for point in points[start + 1 : stop + 1]
                    if point.snapshot_id is not None
                }
            )
            results.append(
                MonthlyReturn(
                    month_end=current,
                    total_return=value_at[current].level / value_at[previous].level - 1,
                    is_proxy=False,
                    source_price_version=",".join(snapshots),
                )
            )
    return tuple(results)


def cash_proxy_returns(
    observations: Iterable[MacroPoint], calendar_month_ends: Iterable[date]
) -> tuple[MonthlyReturn, ...]:
    """DTB3 approximation: mean of the month's daily discount rates (percent) / 100 / 12.

    Missing observations (NULL) are skipped; a month without any value gets no proxy return.
    """
    by_month: dict[tuple[int, int], list[MacroPoint]] = {}
    for point in observations:
        if point.value is not None:
            key = (point.observation_date.year, point.observation_date.month)
            by_month.setdefault(key, []).append(point)
    results = []
    with localcontext(_CONTEXT):
        for end in calendar_month_ends:
            month = by_month.get((end.year, end.month))
            if not month:
                continue
            mean = sum((point.value for point in month), Decimal(0)) / len(month)  # type: ignore[misc]
            snapshots = sorted({point.snapshot_id for point in month})
            results.append(
                MonthlyReturn(end, mean / 100 / 12, True, "fred:DTB3:" + ",".join(snapshots))
            )
    return tuple(results)


def splice_cash(
    cash_etf: tuple[MonthlyReturn, ...], proxy: tuple[MonthlyReturn, ...]
) -> tuple[MonthlyReturn, ...]:
    """Proxy fills only months before the cash ETF's first return; afterwards only the ETF."""
    if not cash_etf:
        return proxy
    first = min(item.month_end for item in cash_etf)
    before = tuple(item for item in proxy if item.month_end < first)
    return tuple(sorted(before + cash_etf, key=lambda item: item.month_end))


def eligible_assets(
    month_ends_by_ticker: Mapping[str, Iterable[date]],
    as_of: date,
    minimum_months: int = MINIMUM_ELIGIBLE_MONTHS,
) -> tuple[str, ...]:
    """Tickers with at least `minimum_months` monthly returns up to the end of as_of's month."""
    return tuple(
        ticker
        for ticker, ends in month_ends_by_ticker.items()
        if sum(1 for end in ends if (end.year, end.month) <= (as_of.year, as_of.month))
        >= minimum_months
    )


@dataclass(frozen=True, slots=True)
class UniverseReturns:
    returns: dict[str, tuple[MonthlyReturn, ...]]
    anomalies: dict[str, tuple[IndexPoint, ...]]
    failures: dict[str, str]


def compute_universe_returns(
    prices: Mapping[str, Iterable[PricePoint]],
    *,
    calendar_ticker: str,
    cash_ticker: str,
    cash_proxy: Iterable[MacroPoint],
) -> UniverseReturns:
    """Each ticker is computed independently; only the calendar ticker's dates are shared."""
    indexes: dict[str, tuple[IndexPoint, ...]] = {}
    failures: dict[str, str] = {}
    for ticker, points in prices.items():
        try:
            indexes[ticker] = total_return_index(points)
        except UnlinkedPriceError as error:
            failures[ticker] = str(error)
    if not indexes.get(calendar_ticker):
        raise ValueError(f"calendar ticker {calendar_ticker} has no prices")
    ends = month_ends(point.trading_date for point in indexes[calendar_ticker])
    returns = {ticker: monthly_returns(index, ends) for ticker, index in indexes.items()}
    if cash_ticker in prices:
        returns[cash_ticker] = splice_cash(
            returns.get(cash_ticker, ()), cash_proxy_returns(cash_proxy, ends)
        )
    anomalies = {ticker: return_anomalies(index) for ticker, index in indexes.items()}
    return UniverseReturns(returns, anomalies, failures)

"""Run every strategy under every rebalancing rule and compare them on a common period."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from asset_frame.analytics.risk import WINDOW_MONTHS
from asset_frame.backtest.engine import RULES, MonthResult, run_strategy
from asset_frame.backtest.metrics import Performance, Relative, performance, relative
from asset_frame.backtest.strategies import Strategy

BENCHMARKS = ("bench_spy", "bench_6040")
CALENDAR_TICKER = "SPY"


@dataclass(frozen=True, slots=True)
class Row:
    strategy: str
    rule: str
    start: date
    end: date
    performance: Performance
    versus: dict[str, Relative]
    mean_turnover: float


@dataclass(frozen=True, slots=True)
class BacktestResult:
    months: dict[tuple[str, str], tuple[MonthResult, ...]]
    common_months: tuple[date, ...]
    rows: tuple[Row, ...]


def run_backtest(
    strategies: tuple[Strategy, ...],
    returns: dict[str, dict[date, float]],
    *,
    cash_ticker: str,
    window_months: int = WINDOW_MONTHS,
) -> BacktestResult:
    """Rows cover the months in which every strategy under every rule holds its full intended
    weights (coverage 1), so all rows describe the same period and the same composition."""
    calendar = sorted(returns[CALENDAR_TICKER])
    months = {
        (strategy.id, rule): run_strategy(strategy, returns, calendar, rule, window_months)
        for strategy in strategies
        for rule in RULES
    }
    complete = [
        {r.month for r in results if r.coverage >= 1 - 1e-12} for results in months.values()
    ]
    common = tuple(sorted(set.intersection(*complete))) if complete else ()
    if len(common) < 2:
        raise ValueError("no common period with full coverage for every strategy")
    lookup = {key: {r.month: r for r in results} for key, results in months.items()}
    cash = [returns[cash_ticker][month] for month in common]
    rows = []
    for (strategy_id, rule), by_month in lookup.items():
        series = [by_month[month].total_return for month in common]
        versus = {
            name: relative(series, [lookup[name, rule][month].total_return for month in common])
            for name in BENCHMARKS
            if (name, rule) in lookup
        }
        rows.append(
            Row(
                strategy_id,
                rule,
                common[0],
                common[-1],
                performance(series, cash),
                versus,
                sum(by_month[m].turnover for m in common) / len(common),
            )
        )
    return BacktestResult(months, common, tuple(rows))

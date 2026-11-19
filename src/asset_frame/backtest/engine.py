"""Monthly backtest of a strategy under a rebalancing rule. Pure functions; no costs or taxes.

Concept card: docs/concepts/strategic_allocation.md.

At the start of month m the eligible assets are those with at least 13 monthly returns
before m and a return in m. Weights drift with returns between rebalances; a change in the
eligible set forces a rebalance.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from asset_frame.backtest.strategies import Strategy, target_weights

CALC_VERSION = "backtest_v1"
MINIMUM_HISTORY_MONTHS = 13
BAND = 0.05
QUARTER_START_MONTHS = (1, 4, 7, 10)
RULES = ("monthly", "quarterly", "band")


@dataclass(frozen=True, slots=True)
class MonthResult:
    month: date
    total_return: float
    coverage: float
    turnover: float


def run_strategy(
    strategy: Strategy,
    returns: Mapping[str, Mapping[date, float]],
    months: Sequence[date],
    rule: str,
) -> tuple[MonthResult, ...]:
    """`months` is the calendar (sorted month ends); `rule` is monthly, quarterly or band."""
    if rule not in RULES:
        raise ValueError(f"unknown rebalancing rule {rule}")
    history = {ticker: sorted(by_month) for ticker, by_month in returns.items()}
    results = []
    weights: dict[str, float] = {}
    for month in months:
        eligible = [
            ticker
            for ticker, dates in history.items()
            if bisect_left(dates, month) >= MINIMUM_HISTORY_MONTHS and month in returns[ticker]
        ]
        target, coverage = target_weights(strategy, eligible)
        if not target:
            weights = {}
            continue
        initial = not weights
        if initial or set(weights) != set(target) or _rebalance_due(rule, month, weights, target):
            turnover = 0.0 if initial else _half_turnover(weights, target)
            weights = target
        else:
            turnover = 0.0
        portfolio = sum(weights[t] * returns[t][month] for t in weights)
        results.append(MonthResult(month, portfolio, coverage, turnover))
        weights = {t: w * (1 + returns[t][month]) / (1 + portfolio) for t, w in weights.items()}
    return tuple(results)


def _rebalance_due(
    rule: str, month: date, weights: Mapping[str, float], target: Mapping[str, float]
) -> bool:
    if rule == "monthly":
        return True
    if rule == "quarterly":
        return month.month in QUARTER_START_MONTHS
    return any(abs(weights[t] - target[t]) > BAND for t in target)


def _half_turnover(before: Mapping[str, float], after: Mapping[str, float]) -> float:
    tickers = before.keys() | after.keys()
    return sum(abs(after.get(t, 0.0) - before.get(t, 0.0)) for t in tickers) / 2

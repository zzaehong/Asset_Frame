"""Performance statistics on monthly returns. Pure functions on floats.

Concept cards: docs/concepts/{cagr_calmar,sharpe_ratio,sortino_ratio,information_ratio}.md.

Excess returns are measured over the cash return of the same month.
Figures are annualised from monthly data.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import prod, sqrt
from statistics import fmean, stdev

from asset_frame.analytics.risk import PERIODS_PER_YEAR, max_drawdown


@dataclass(frozen=True, slots=True)
class Performance:
    months: int
    cagr: float
    volatility: float
    sharpe: float | None
    sortino: float | None
    calmar: float | None
    max_drawdown: float


@dataclass(frozen=True, slots=True)
class Relative:
    excess_cagr: float
    tracking_error: float
    information_ratio: float | None


def performance(returns: Sequence[float], cash: Sequence[float]) -> Performance:
    if len(returns) != len(cash) or len(returns) < 2:
        raise ValueError("need at least 2 months and one cash return per month")
    cagr = prod(1 + r for r in returns) ** (PERIODS_PER_YEAR / len(returns)) - 1
    excess = [r - c for r, c in zip(returns, cash, strict=True)]
    spread = stdev(excess)
    downside = sqrt(sum(min(x, 0.0) ** 2 for x in excess) / len(excess))
    drawdown = max_drawdown(returns)
    return Performance(
        months=len(returns),
        cagr=cagr,
        volatility=stdev(returns) * sqrt(PERIODS_PER_YEAR),
        sharpe=fmean(excess) * sqrt(PERIODS_PER_YEAR) / spread if spread > 0 else None,
        sortino=fmean(excess) * sqrt(PERIODS_PER_YEAR) / downside if downside > 0 else None,
        calmar=cagr / abs(drawdown) if drawdown < 0 else None,
        max_drawdown=drawdown,
    )


def relative(returns: Sequence[float], benchmark: Sequence[float]) -> Relative:
    if len(returns) != len(benchmark) or len(returns) < 2:
        raise ValueError("need at least 2 months and equal lengths")
    active = [r - b for r, b in zip(returns, benchmark, strict=True)]
    spread = stdev(active)
    own = prod(1 + r for r in returns) ** (PERIODS_PER_YEAR / len(returns)) - 1
    bench = prod(1 + b for b in benchmark) ** (PERIODS_PER_YEAR / len(benchmark)) - 1
    return Relative(
        excess_cagr=own - bench,
        tracking_error=spread * sqrt(PERIODS_PER_YEAR),
        information_ratio=fmean(active) * sqrt(PERIODS_PER_YEAR) / spread if spread > 0 else None,
    )

"""Risk statistics on monthly total returns. Pure functions on floats; no I/O.

Concept cards: docs/concepts/{volatility,max_drawdown,historical_var,correlation,
risk_contribution}.md. Inputs are monthly total returns (fractions, 0.01 = 1%), so every
statistic is a monthly-data estimate: drawdowns inside a month are not seen.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from math import floor, sqrt
from statistics import correlation, covariance, stdev

CALC_VERSION = "risk_v1"
PERIODS_PER_YEAR = 12
WINDOW_MONTHS = 36
VAR_LEVEL = 0.95

Pair = tuple[str, str]


def annualized_volatility(returns: Sequence[float]) -> float:
    """Sample standard deviation (ddof=1) of monthly returns times sqrt(12)."""
    if len(returns) < 2:
        raise ValueError("volatility needs at least 2 returns")
    return stdev(returns) * sqrt(PERIODS_PER_YEAR)


def max_drawdown(returns: Sequence[float]) -> float:
    """Largest peak-to-trough fall of wealth that starts at 1; 0 or negative."""
    wealth = peak = 1.0
    worst = 0.0
    for value in returns:
        wealth *= 1 + value
        peak = max(peak, wealth)
        worst = min(worst, wealth / peak - 1)
    return worst


def historical_var(returns: Sequence[float], level: float = VAR_LEVEL) -> float:
    """One-month historical VaR as a positive loss: minus the (1-level) empirical quantile.

    The quantile uses linear interpolation between order statistics (position (n-1)*(1-level)).
    """
    if not 0 < level < 1:
        raise ValueError("level must be between 0 and 1")
    if not returns:
        raise ValueError("VaR needs at least 1 return")
    ordered = sorted(returns)
    position = (len(ordered) - 1) * (1 - level)
    lower = floor(position)
    upper = min(lower + 1, len(ordered) - 1)
    quantile = ordered[lower] + (position - lower) * (ordered[upper] - ordered[lower])
    return -quantile


def trailing_months(
    month_ends: Sequence[date], as_of: date, window: int = WINDOW_MONTHS
) -> tuple[date, ...]:
    """The last `window` month ends on or before as_of; empty if fewer exist."""
    eligible = sorted(month for month in month_ends if month <= as_of)
    return tuple(eligible[-window:]) if len(eligible) >= window else ()


def aligned_window(
    series: Mapping[str, Mapping[date, float]], months: Sequence[date]
) -> dict[str, list[float]]:
    """Returns over `months` for each ticker that has every month; others are left out."""
    return {
        ticker: [by_month[month] for month in months]
        for ticker, by_month in series.items()
        if all(month in by_month for month in months)
    }


def correlation_matrix(window: Mapping[str, Sequence[float]]) -> dict[Pair, float | None]:
    """Pearson correlation of each pair; None when either series is constant."""
    result: dict[Pair, float | None] = {}
    for first, a in window.items():
        for second, b in window.items():
            try:
                result[first, second] = correlation(a, b)
            except ValueError:  # statistics raises StatisticsError (a ValueError) for constants
                result[first, second] = None
    return result


def covariance_matrix(window: Mapping[str, Sequence[float]]) -> dict[Pair, float]:
    """Sample covariance (ddof=1) of each pair."""
    return {
        (first, second): covariance(a, b)
        for first, a in window.items()
        for second, b in window.items()
    }


def risk_contributions(weights: Mapping[str, float], cov: Mapping[Pair, float]) -> dict[str, float]:
    """Share of portfolio variance from each asset: w_i * (cov w)_i / (w' cov w). Sums to 1."""
    marginal = {
        first: sum(cov[first, second] * weight for second, weight in weights.items())
        for first in weights
    }
    variance = sum(weights[ticker] * marginal[ticker] for ticker in weights)
    if variance <= 0:
        raise ValueError("portfolio variance must be positive")
    return {ticker: weights[ticker] * marginal[ticker] / variance for ticker in weights}

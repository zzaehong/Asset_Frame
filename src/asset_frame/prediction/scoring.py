"""Scoring of ledger predictions once HORIZON_MONTHS months have passed."""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from datetime import date

from asset_frame.prediction.models import HORIZON_MONTHS

MIN_ASSETS = 6  # top 3 and bottom 3 must not overlap
MDE_MIN_SAMPLES = 5
MDE_FACTOR = 2.8  # (z_0.975 + z_0.8) for a two-sided 5% test with 80% power


def realized_returns(
    returns: Mapping[str, Mapping[date, float]], tickers: Sequence[str], months: Sequence[date]
) -> dict[str, float]:
    """Cumulative return over `months` for each ticker that has all of them."""
    result = {}
    for ticker in tickers:
        by_month = returns.get(ticker, {})
        if all(month in by_month for month in months):
            growth = 1.0
            for month in months:
                growth *= 1 + by_month[month]
            result[ticker] = growth - 1
    return result


def horizon_months(month_ends: Sequence[date], as_of: date) -> tuple[date, ...] | None:
    """The HORIZON_MONTHS month ends after `as_of`, or None while they are not all known."""
    later = sorted(month for month in month_ends if month > as_of)
    return tuple(later[:HORIZON_MONTHS]) if len(later) >= HORIZON_MONTHS else None


def _ranks(values: Sequence[float]) -> list[float]:
    """1-based ranks, ties share their average rank."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
            end += 1
        for index in order[position : end + 1]:
            ranks[index] = (position + end) / 2 + 1
        position = end + 1
    return ranks


def rank_ic(predicted_order: Sequence[str], realized: Mapping[str, float]) -> float | None:
    """Spearman correlation between predicted order (best first) and realized returns."""
    tickers = [t for t in predicted_order if t in realized]
    if len(tickers) < MIN_ASSETS:
        return None
    predicted_score = [float(len(tickers) - i) for i in range(len(tickers))]
    try:
        return statistics.correlation(
            _ranks(predicted_score), _ranks([realized[t] for t in tickers])
        )
    except statistics.StatisticsError:  # all realized returns equal
        return None


def top_bottom_spread(
    predicted_order: Sequence[str], realized: Mapping[str, float]
) -> float | None:
    """Mean realized return of the predicted top 3 minus the predicted bottom 3."""
    tickers = [t for t in predicted_order if t in realized]
    if len(tickers) < MIN_ASSETS:
        return None
    top, bottom = tickers[:3], tickers[-3:]
    return statistics.fmean(realized[t] for t in top) - statistics.fmean(
        realized[t] for t in bottom
    )


def brier(probability_positive: float, outcome_positive: bool) -> float:
    return (probability_positive - (1.0 if outcome_positive else 0.0)) ** 2


def mean_with_mde(values: Sequence[float]) -> tuple[float, float | None]:
    """(mean, minimum detectable mean difference from 0 at 80% power); MDE None below 5 samples.

    Monthly predictions have overlapping horizons, so the real number of independent samples is
    smaller than len(values); the MDE is therefore optimistic.
    """
    mean = statistics.fmean(values)
    if len(values) < MDE_MIN_SAMPLES:
        return mean, None
    return mean, MDE_FACTOR * statistics.stdev(values) / len(values) ** 0.5

"""Ranking models for the ledger. Every model answers the same question at month end t: rank the
assets by expected cumulative return over the next HORIZON_MONTHS months, and give the probability
that the SPY-IEF trailing 36-month correlation is positive at t + HORIZON_MONTHS."""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from datetime import date

HORIZON_MONTHS = 3
MOMENTUM_MONTHS = 12
MODELS = ("momentum_12_1", "equal_rank")


def momentum_ranking(
    returns: Mapping[str, Mapping[date, float]], tickers: Sequence[str], month_ends: Sequence[date]
) -> list[str]:
    """Best to worst by the cumulative return of the 12 months before the latest one (12-1).

    `month_ends` ends at the decision month t; t itself is skipped. Assets without all 11 months
    are left out. Ties keep the order of `tickers`.
    """
    window = list(month_ends)[-MOMENTUM_MONTHS:-1]
    if len(window) < MOMENTUM_MONTHS - 1:
        return []
    scores: dict[str, float] = {}
    for ticker in tickers:
        by_month = returns.get(ticker, {})
        if all(month in by_month for month in window):
            growth = 1.0
            for month in window:
                growth *= 1 + by_month[month]
            scores[ticker] = growth - 1
    return sorted(scores, key=lambda ticker: -scores[ticker])


def random_ranking(tickers: Sequence[str], as_of: date) -> list[str]:
    """Reference model: a shuffle fixed by the decision date, so reruns give the same ranking."""
    ranking = list(tickers)
    random.Random(as_of.isoformat()).shuffle(ranking)
    return ranking


def persistence_probability(correlation: float | None) -> float | None:
    """Hard forecast that the sign stays: 1.0 if the current correlation is positive, else 0.0."""
    if correlation is None:
        return None
    return 1.0 if correlation > 0 else 0.0

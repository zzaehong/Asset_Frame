"""Weights estimated from a return window. Pure functions on floats, standard library only.

Concept cards: docs/concepts/{mean_variance,risk_contribution}.md. All weights are long-only and
sum to 1. Iterative solvers stop at a fixed tolerance and raise if they do not converge.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import sqrt
from statistics import stdev

from asset_frame.analytics.risk import Pair

TOLERANCE = 1e-12
MAX_ITERATIONS = 100_000


def inverse_volatility_weights(window: Mapping[str, Sequence[float]]) -> dict[str, float]:
    """Weight proportional to 1 / sample standard deviation."""
    inverse = {}
    for ticker, values in window.items():
        spread = stdev(values)
        if spread <= 0:
            raise ValueError(f"{ticker} has zero volatility in the window")
        inverse[ticker] = 1 / spread
    total = sum(inverse.values())
    return {ticker: value / total for ticker, value in inverse.items()}


def equal_risk_contribution_weights(
    cov: Mapping[Pair, float], tickers: Sequence[str]
) -> dict[str, float]:
    """Weights whose risk contributions are all equal (cyclical coordinate descent).

    Solves y_i * (cov y)_i = 1/n one coordinate at a time, from the positive root of
    cov_ii y_i^2 + c_i y_i - 1/n = 0 with c_i = sum_{j != i} cov_ij y_j, then normalises y.
    """
    n = len(tickers)
    y = {t: 1 / sqrt(cov[t, t]) for t in tickers}
    for _ in range(MAX_ITERATIONS):
        largest_move = 0.0
        for ticker in tickers:
            c = sum(cov[ticker, other] * y[other] for other in tickers if other != ticker)
            new = (-c + sqrt(c * c + 4 * cov[ticker, ticker] / n)) / (2 * cov[ticker, ticker])
            largest_move = max(largest_move, abs(new - y[ticker]))
            y[ticker] = new
        if largest_move < TOLERANCE:
            total = sum(y.values())
            return {t: value / total for t, value in y.items()}
    raise ValueError("equal risk contribution did not converge")


def minimum_variance_weights(
    cov: Mapping[Pair, float], tickers: Sequence[str], max_weight: float
) -> dict[str, float]:
    """Minimise w' cov w with 0 <= w_i <= max_weight and sum w = 1 (pairwise coordinate steps).

    Each step moves weight from the asset with the highest marginal variance to the lowest and
    is exact along that line. The cap is raised to 1/n when n * max_weight < 1 (infeasible).
    """
    n = len(tickers)
    cap = max(max_weight, 1 / n)
    w = [1 / n] * n
    names = list(tickers)
    matrix = [[cov[a, b] for b in names] for a in names]
    gradient = [sum(matrix[i][k] * w[k] for k in range(n)) for i in range(n)]
    for _ in range(MAX_ITERATIONS):
        receivers = [i for i in range(n) if w[i] < cap - TOLERANCE]
        givers = [j for j in range(n) if w[j] > TOLERANCE]
        if not receivers or not givers:
            break
        i = min(receivers, key=lambda index: gradient[index])
        j = max(givers, key=lambda index: gradient[index])
        gap = gradient[j] - gradient[i]
        if gap <= TOLERANCE:
            break
        curvature = matrix[i][i] + matrix[j][j] - 2 * matrix[i][j]
        limit = min(cap - w[i], w[j])
        step = limit if curvature <= 0 else min(limit, gap / curvature)
        w[i] += step
        w[j] -= step
        for k in range(n):
            gradient[k] += step * (matrix[k][i] - matrix[k][j])
    else:
        raise ValueError("minimum variance did not converge")
    return dict(zip(names, w, strict=True))

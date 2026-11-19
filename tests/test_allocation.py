from itertools import product

import pytest

from asset_frame.analytics.allocation import (
    equal_risk_contribution_weights,
    inverse_volatility_weights,
    minimum_variance_weights,
)
from asset_frame.analytics.risk import covariance_matrix, risk_contributions


def diagonal(variances: dict[str, float]) -> dict[tuple[str, str], float]:
    return {(a, b): (variances[a] if a == b else 0.0) for a in variances for b in variances}


def test_inverse_volatility_hand_calculation() -> None:
    window = {"A": [0.01, -0.01], "B": [0.02, -0.02]}  # std ratio 1 : 2
    weights = inverse_volatility_weights(window)
    assert weights == pytest.approx({"A": 2 / 3, "B": 1 / 3})
    with pytest.raises(ValueError, match="zero volatility"):
        inverse_volatility_weights({"A": [0.01, 0.01], "B": [0.02, -0.02]})


def test_erc_uncorrelated_assets_are_weighted_by_inverse_volatility() -> None:
    cov = diagonal({"A": 0.01, "B": 0.04})  # volatilities 10% and 20%
    weights = equal_risk_contribution_weights(cov, ["A", "B"])
    assert weights == pytest.approx({"A": 2 / 3, "B": 1 / 3})


def test_erc_equalises_risk_contributions_with_correlation() -> None:
    window = {
        "A": [0.03, -0.02, 0.01, 0.04, -0.03, 0.02],
        "B": [0.01, 0.02, -0.01, 0.00, 0.01, -0.02],
        "C": [-0.02, 0.05, 0.03, -0.04, 0.02, 0.01],
        "D": [0.00, 0.01, 0.00, 0.01, -0.01, 0.01],
    }
    cov = covariance_matrix(window)
    weights = equal_risk_contribution_weights(cov, list(window))
    shares = risk_contributions(weights, cov)
    assert sum(weights.values()) == pytest.approx(1.0)
    assert all(value > 0 for value in weights.values())
    assert list(shares.values()) == pytest.approx([0.25] * 4, abs=1e-8)


def test_min_variance_two_uncorrelated_assets_matches_the_closed_form() -> None:
    cov = diagonal({"A": 0.01, "B": 0.04})
    weights = minimum_variance_weights(cov, ["A", "B"], max_weight=1.0)
    assert weights["A"] == pytest.approx(0.04 / 0.05)  # sigma_B^2 / (sigma_A^2 + sigma_B^2)


def test_min_variance_respects_the_cap_and_infeasible_cap_falls_back_to_equal() -> None:
    cov = diagonal({"A": 0.01, "B": 0.04})
    capped = minimum_variance_weights(cov, ["A", "B"], max_weight=0.6)
    assert capped == pytest.approx({"A": 0.6, "B": 0.4})
    tight = minimum_variance_weights(cov, ["A", "B"], max_weight=0.3)  # 2 * 0.3 < 1
    assert tight == pytest.approx({"A": 0.5, "B": 0.5})


def test_min_variance_matches_a_grid_search_on_three_correlated_assets() -> None:
    window = {
        "A": [0.03, -0.02, 0.01, 0.04, -0.03, 0.02],
        "B": [0.02, -0.01, 0.01, 0.03, -0.02, 0.01],
        "C": [-0.01, 0.02, 0.00, -0.02, 0.03, 0.01],
    }
    cov = covariance_matrix(window)
    cap = 0.5
    weights = minimum_variance_weights(cov, list(window), cap)

    def variance(w: dict[str, float]) -> float:
        return sum(w[a] * w[b] * cov[a, b] for a in w for b in w)

    best = min(
        variance({"A": a / 100, "B": b / 100, "C": (100 - a - b) / 100})
        for a, b in product(range(0, 51), repeat=2)
        if 50 >= 100 - a - b >= 0
    )
    assert sum(weights.values()) == pytest.approx(1.0)
    assert max(weights.values()) <= cap + 1e-12
    assert variance(weights) <= best + 1e-12

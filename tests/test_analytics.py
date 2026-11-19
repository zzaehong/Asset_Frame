from datetime import date
from decimal import Decimal

import pytest

from asset_frame.analytics.risk import (
    aligned_window,
    annualized_volatility,
    correlation_matrix,
    covariance_matrix,
    historical_var,
    max_drawdown,
    risk_contributions,
    trailing_months,
)
from asset_frame.universe import UniverseAsset
from asset_frame.universe_jobs import analyze_universe


def month_list(count: int) -> list[date]:
    return [date(2020 + n // 12, n % 12 + 1, 28) for n in range(count)]


def test_volatility_is_sample_std_times_sqrt_12() -> None:
    # sample variance of [0.1, -0.1] is 0.02, so 12 * 0.02 = 0.24
    assert annualized_volatility([0.1, -0.1]) == pytest.approx(0.24**0.5)
    with pytest.raises(ValueError):
        annualized_volatility([0.1])


def test_max_drawdown_hand_calculation() -> None:
    # wealth 1.1, 0.88, 0.924, 0.8316; peak 1.1; worst 0.8316 / 1.1 - 1
    assert max_drawdown([0.1, -0.2, 0.05, -0.1]) == pytest.approx(-0.244)
    assert max_drawdown([0.01, 0.02]) == 0.0


def test_var_lands_on_an_order_statistic_and_interpolates_between() -> None:
    # n = 21: position (21-1)*0.05 = 1.0, the second-lowest return
    exact = [-0.10, -0.05, *([0.01] * 19)]
    assert historical_var(exact) == pytest.approx(0.05)
    # n = 11: position 0.5, halfway between the two lowest
    between = [-0.10, -0.06, *([0.01] * 9)]
    assert historical_var(between) == pytest.approx(0.08)


def test_window_needs_every_month_and_drops_incomplete_assets() -> None:
    months = month_list(40)
    assert trailing_months(months, months[-1], 36) == tuple(months[-36:])
    assert trailing_months(months[:10], months[-1], 36) == ()
    window = months[-3:]
    series = {
        "FULL": {m: 0.01 for m in window},
        "SHORT": {m: 0.01 for m in window[1:]},
    }
    assert list(aligned_window(series, window)) == ["FULL"]


def test_correlation_signs_and_constant_series() -> None:
    window = {
        "A": [1.0, 2.0, 3.0],
        "B": [2.0, 4.0, 6.0],
        "C": [3.0, 2.0, 1.0],
        "K": [1.0, 1.0, 1.0],
    }
    matrix = correlation_matrix(window)
    assert matrix["A", "B"] == pytest.approx(1.0)
    assert matrix["A", "C"] == pytest.approx(-1.0)
    assert matrix["A", "K"] is None


def test_risk_contribution_hand_calculation_and_properties() -> None:
    # uncorrelated, volatilities 10% and 20%, equal weights: shares 0.0025/0.0125 and 0.01/0.0125
    cov = {("A", "A"): 0.01, ("B", "B"): 0.04, ("A", "B"): 0.0, ("B", "A"): 0.0}
    shares = risk_contributions({"A": 0.5, "B": 0.5}, cov)
    assert shares == pytest.approx({"A": 0.2, "B": 0.8})
    # weights proportional to 1 / volatility equalise the shares (the idea behind erc)
    equal = risk_contributions({"A": 2 / 3, "B": 1 / 3}, cov)
    assert equal["A"] == pytest.approx(equal["B"])


def test_portfolio_variance_matches_the_weighted_return_series() -> None:
    window = {"A": [0.02, -0.01, 0.03, 0.00], "B": [0.01, 0.02, -0.02, 0.01]}
    weights = {"A": 0.3, "B": 0.7}
    cov = covariance_matrix(window)
    portfolio = [0.3 * a + 0.7 * b for a, b in zip(window["A"], window["B"], strict=True)]
    variance = sum(weights[i] * weights[j] * cov[i, j] for i in weights for j in weights)
    assert variance == pytest.approx(annualized_volatility(portfolio) ** 2 / 12)
    assert sum(risk_contributions(weights, cov).values()) == pytest.approx(1.0)


class StubStore:
    def __init__(self, returns: dict[str, dict[date, Decimal]]) -> None:
        self._returns = returns

    def latest_returns(self) -> dict[str, dict[date, Decimal]]:
        return self._returns


def test_analysis_uses_the_spy_calendar_and_excludes_short_histories() -> None:
    months = month_list(40)
    wave = [Decimal("0.02"), Decimal("-0.01"), Decimal("0.03")]
    returns = {
        "SPY": {m: wave[n % 3] for n, m in enumerate(months)},
        "IEF": {m: wave[(n + 1) % 3] for n, m in enumerate(months)},
        "NEW": {m: wave[n % 3] for n, m in enumerate(months[-10:])},
    }
    assets = tuple(
        UniverseAsset(t, t, 1, t.lower(), "anchor", None, date(2020, 1, 1), None)
        for t in ("SPY", "IEF", "NEW")
    )

    result = analyze_universe(assets, store=StubStore(returns))  # type: ignore[arg-type]

    assert result.as_of == months[-1]
    assert result.excluded == ("NEW",)
    assert set(result.risk_contribution) == {"SPY", "IEF"}
    assert sum(result.risk_contribution.values()) == pytest.approx(1.0)
    assert {row.ticker: row.months for row in result.assets} == {"SPY": 40, "IEF": 40, "NEW": 10}

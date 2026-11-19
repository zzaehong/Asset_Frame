from datetime import date

import pytest

from asset_frame.regime.rules import (
    available,
    correlation_regime,
    growth_inflation_quadrant,
    inflation_direction,
    rule_cfnai_sahm,
    rule_indpro_sahm,
    sahm_indicator,
    year_over_year,
)


def months(values: list[float], start: int = 0) -> dict[int, float]:
    return {start + i: value for i, value in enumerate(values)}


def test_available_hides_values_released_after_the_decision_date() -> None:
    series = [
        (date(2026, 1, 1), date(2026, 2, 6), 4.0),
        (date(2026, 2, 1), date(2026, 3, 6), 4.1),
    ]

    assert len(available(series, date(2026, 2, 28))) == 1
    assert len(available(series, date(2026, 3, 6))) == 2
    assert available(series, date(2026, 1, 31)) == {}


FIRING = months([4.0] * 13 + [4.5, 5.0])  # 15 months, latest = month 14
CALM = months([4.0] * 15)


def test_sahm_indicator_hand_computed() -> None:
    # latest 3-month average = (4.0 + 4.5 + 5.0) / 3 = 4.5; the minimum of the previous 12
    # 3-month averages is 4.0 -> 0.5 percentage points
    assert sahm_indicator(FIRING) == pytest.approx(0.5)
    assert sahm_indicator(CALM) == pytest.approx(0.0)


def test_sahm_needs_complete_history() -> None:
    assert sahm_indicator({}) is None
    assert sahm_indicator(months([4.0] * 14)) is None  # 12 prior averages need 15 months
    gap = dict(CALM)
    del gap[5]
    assert sahm_indicator(gap) is None


def test_year_over_year_and_inflation_direction() -> None:
    assert year_over_year(months([100.0] * 12 + [103.0])) == pytest.approx(0.03)
    assert year_over_year(months([100.0] * 5)) is None
    # y/y 2% at month 12, 3% at month 15 -> rising
    cpi = {0: 100.0, 3: 100.0, 12: 102.0, 15: 103.0}
    assert inflation_direction(cpi) == 1
    assert inflation_direction({0: 100.0, 3: 100.0, 12: 103.0, 15: 102.0}) == -1
    assert inflation_direction({12: 102.0, 15: 103.0}) is None


def test_recession_rules_need_both_signals() -> None:
    assert rule_cfnai_sahm({14: -0.8}, FIRING) is True
    assert rule_cfnai_sahm({14: -0.8}, CALM) is False
    assert rule_cfnai_sahm({14: -0.6}, FIRING) is False
    assert rule_cfnai_sahm({}, FIRING) is None


def test_indpro_rule_fires_when_both_signals_align() -> None:
    assert rule_indpro_sahm({2: 100.0, 14: 98.0}, FIRING) is True
    assert rule_indpro_sahm({2: 100.0, 14: 101.0}, FIRING) is False
    assert rule_indpro_sahm({2: 100.0, 14: 98.0}, CALM) is False
    assert rule_indpro_sahm({14: 98.0}, FIRING) is None


def test_quadrant_and_correlation_regime() -> None:
    rising = {0: 100.0, 3: 100.0, 12: 102.0, 15: 103.0}
    assert growth_inflation_quadrant({15: 0.1}, rising) == "growth_up_inflation_up"
    assert growth_inflation_quadrant({15: -0.1}, rising) == "growth_down_inflation_up"
    assert growth_inflation_quadrant({}, rising) is None
    assert correlation_regime(0.2) == "stock_bond_positive"
    assert correlation_regime(-0.2) == "stock_bond_negative"
    assert correlation_regime(None) is None

from datetime import date

import pytest

from asset_frame.regime.performance import regime_performance
from asset_frame.regime.replay import RegimeRow


def row(month_end: date, quadrant: str | None, flag: bool | None = None) -> RegimeRow:
    return RegimeRow(
        month_end=month_end,
        sahm=None,
        indpro_yoy=None,
        cfnai_ma3=None,
        indpro_sahm=flag,
        cfnai_sahm=None,
        quadrant=quadrant,
        stock_bond_correlation=None,
        correlation_regime=None,
        nber_recession=False,
    )


JAN, FEB, MAR, APR = date(2020, 1, 31), date(2020, 2, 29), date(2020, 3, 31), date(2020, 4, 30)
RETURNS = {
    "A": {JAN: 0.9, FEB: 0.10, MAR: -0.02, APR: 0.04},
    "B": {JAN: 0.9, FEB: 0.01, APR: 0.02},  # March missing
}


def test_return_is_attributed_to_the_regime_known_one_month_earlier() -> None:
    rows = [row(JAN, "up"), row(FEB, "down"), row(MAR, "up")]

    result = regime_performance(rows, RETURNS)["quadrant"]

    up = result["up"]  # January label -> February return, March label -> April return
    assert up["months"] == 2
    assert up["assets"]["A"]["mean"] == pytest.approx((0.10 + 0.04) / 2)
    assert up["assets"]["A"]["hit_rate"] == 1.0
    assert result["down"]["assets"]["A"] == {"mean": -0.02, "hit_rate": 0.0, "months": 1}


def test_missing_month_shrinks_that_assets_sample_only() -> None:
    result = regime_performance([row(JAN, "x"), row(FEB, "x")], RETURNS)["quadrant"]["x"]

    assert result["months"] == 2
    assert result["assets"]["A"]["months"] == 2
    assert result["assets"]["B"]["months"] == 1  # March return absent


def test_unlabelled_and_last_months_are_skipped() -> None:
    rows = [row(JAN, None), row(APR, "up")]  # no label; no month after April

    assert regime_performance(rows, RETURNS)["quadrant"] == {}


def test_boolean_flag_axis_uses_its_own_labels() -> None:
    result = regime_performance([row(JAN, None, True), row(FEB, None, False)], RETURNS)

    assert set(result["indpro_sahm"]) == {"True", "False"}

from datetime import date

import pytest

from asset_frame.regime.equity import bear_state

JAN, FEB, MAR, APR, MAY = (
    date(2020, m, d) for m, d in [(1, 31), (2, 28), (3, 31), (4, 30), (5, 29)]
)
LEVELS = [
    (date(2020, 1, 15), 100.0),
    (date(2020, 1, 31), 110.0),  # peak
    (date(2020, 2, 14), 95.0),  # -13.6%
    (date(2020, 2, 28), 100.0),
    (date(2020, 3, 10), 85.0),  # -22.7%: the bear market starts, 85 is the low
    (date(2020, 3, 31), 99.0),  # +16.5% from the low: still a bear market
    (date(2020, 4, 30), 103.0),  # +21.2% from the low: a new bull market, the peak resets to 103
    (date(2020, 5, 29), 100.0),
]


def test_bear_market_starts_at_minus_20_and_ends_at_plus_20_from_the_low() -> None:
    result = bear_state(LEVELS, [JAN, FEB, MAR, APR, MAY])

    assert result is not None
    assert result["bear"] == [False, False, True, False, False]
    assert result["worst_drawdown"] == pytest.approx(
        [0.0, 95 / 110 - 1, 85 / 110 - 1, 0.0, 100 / 103 - 1], abs=1e-4
    )
    assert result["month_end_drawdown"][2] == pytest.approx(
        99 / 110 - 1, abs=1e-4
    )  # still from the old peak


def test_old_peak_does_not_keep_a_recovered_market_in_a_bear_market() -> None:
    result = bear_state(LEVELS, [MAY])

    assert result is not None
    assert result["bear"] == [False]  # May is 9% below the January peak but the bear market ended


def test_entry_boundary_is_inclusive_despite_float_noise() -> None:
    result = bear_state([(date(2020, 1, 2), 100.0), (date(2020, 1, 31), 80.0)], [JAN])

    assert result is not None and result["bear"] == [True]


def test_months_without_prices_and_empty_input() -> None:
    assert bear_state([], [JAN]) is None
    result = bear_state([(date(2020, 1, 31), 100.0)], [JAN, FEB])
    assert result is not None
    assert result["bear"] == [False, None]

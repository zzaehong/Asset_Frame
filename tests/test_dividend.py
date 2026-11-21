from datetime import date
from decimal import Decimal

import pytest

from asset_frame.analytics.dividend import trailing_dividend_yield

D = Decimal
AS_OF = date(2026, 10, 30)
LONG_AGO = date(2020, 1, 1)


def test_yield_sums_the_last_twelve_months_over_the_close() -> None:
    dividends = [
        (date(2025, 11, 1), D("1.0")),
        (date(2026, 2, 1), D("1.0")),
        (date(2026, 8, 1), D("2.0")),
    ]
    result = trailing_dividend_yield(dividends, [], D("200"), AS_OF, LONG_AGO)
    assert result is not None
    assert result.annual_per_share == D(4)
    assert float(result.dividend_yield) == pytest.approx(0.02)
    assert result.payments == 3


def test_dividend_on_the_window_start_or_before_is_excluded() -> None:
    dividends = [
        (date(2025, 10, 30), D("5")),
        (date(2025, 10, 1), D("5")),
        (date(2026, 10, 30), D("1")),
    ]
    result = trailing_dividend_yield(dividends, [], D("100"), AS_OF, LONG_AGO)
    assert result is not None and result.annual_per_share == D(1)


def test_same_ex_date_repeated_by_snapshots_counts_once() -> None:
    dividends = [(date(2026, 3, 1), D("1")), (date(2026, 3, 1), D("1"))]
    result = trailing_dividend_yield(dividends, [], D("100"), AS_OF, LONG_AGO)
    assert result is not None and result.payments == 1 and result.annual_per_share == D(1)


def test_later_split_divides_the_earlier_dividend() -> None:
    dividends = [(date(2026, 3, 1), D("2")), (date(2026, 9, 1), D("1"))]
    splits = [(date(2026, 6, 1), D("2"))]
    result = trailing_dividend_yield(dividends, splits, D("50"), AS_OF, LONG_AGO)
    assert result is not None
    assert result.annual_per_share == D(2)  # 2/2 + 1


def test_no_dividends_is_a_zero_yield_not_missing() -> None:
    result = trailing_dividend_yield([], [], D("100"), AS_OF, LONG_AGO)
    assert result is not None and result.dividend_yield == 0 and result.payments == 0


def test_short_history_or_bad_close_gives_none() -> None:
    assert trailing_dividend_yield([], [], D("100"), AS_OF, date(2026, 1, 1)) is None
    assert trailing_dividend_yield([], [], D("0"), AS_OF, LONG_AGO) is None

from datetime import date

import pytest

from asset_frame.regime.market import as_of_values, market_context

JAN, FEB, MAR = date(2020, 1, 31), date(2020, 2, 29), date(2020, 3, 31)


def test_value_is_the_latest_observation_on_or_before_the_month_end() -> None:
    points = [(date(2020, 1, 30), 1.0), (date(2020, 1, 31), None), (date(2020, 2, 27), 2.0)]

    assert as_of_values(points, [JAN, FEB], max_age_days=10) == [1.0, 2.0]


def test_stale_or_future_observations_are_missing_not_carried_forward() -> None:
    points = [(date(2020, 1, 10), 1.0), (date(2020, 3, 5), 3.0)]

    # January 10 is 21 days before Jan 31; the March 5 value is not known on March 31 - 10 days.
    assert as_of_values(points, [JAN, FEB, MAR], max_age_days=10) == [None, None, None]
    assert as_of_values(points, [JAN], max_age_days=31) == [1.0]
    assert as_of_values([(date(2020, 2, 1), 5.0)], [JAN], max_age_days=31) == [None]


def test_market_context_reports_latest_levels_and_changes_hand_computed() -> None:
    months = [date(2019 + i // 12, i % 12 + 1, 28) for i in range(14)]  # 2019-01 .. 2020-02
    fed = [(date(m.year, m.month, 1), 1.0 + 0.1 * i) for i, m in enumerate(months)]
    dollar = [(m, 100.0 + i) for i, m in enumerate(months)]
    result = market_context({"FEDFUNDS": fed, "DTWEXBGS": dollar}, months)

    assert result is not None
    latest = result["latest"]
    assert latest["fed_funds"] == pytest.approx(2.3)
    assert latest["fed_funds_change_6m"] == pytest.approx(0.6)  # 2.3 - 1.7
    assert latest["dollar"] == pytest.approx(113.0)
    assert latest["dollar_change_12m"] == pytest.approx(113.0 / 101.0 - 1)
    assert latest["spread_10y3m"] is None
    assert set(result["series"]) == {"FEDFUNDS", "DTWEXBGS"}


def test_no_data_gives_no_section() -> None:
    assert market_context({}, [JAN]) is None
    assert market_context({"T10Y3M": []}, [JAN]) is None

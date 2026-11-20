from datetime import date

from asset_frame.regime.long import long_month_ends


def test_known_month_end_is_kept_and_earlier_months_use_the_last_calendar_day() -> None:
    known = [date(2000, 3, 31), date(2000, 4, 28)]  # April's last trading day is the 28th

    result = long_month_ends(known, start=date(2000, 1, 1))

    assert result == [date(2000, 1, 31), date(2000, 2, 29), date(2000, 3, 31), date(2000, 4, 28)]


def test_year_boundary_and_empty_input() -> None:
    assert long_month_ends([date(2001, 1, 31)], start=date(2000, 12, 1)) == [
        date(2000, 12, 31),
        date(2001, 1, 31),
    ]
    assert long_month_ends([]) == []

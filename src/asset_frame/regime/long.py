"""Month ends for the long-history regime replay (macro rules reach back before any fund data)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta

LONG_START = date(1962, 1, 1)  # UNRATE first releases start in 1960; Sahm needs ~14 months


def long_month_ends(known: Iterable[date], start: date = LONG_START) -> list[date]:
    """One date per calendar month from `start` through the latest month in `known`.

    A month that has a date in `known` (a return month end, the last trading day) uses that date;
    an earlier month without one uses its last calendar day.
    """
    by_month: dict[tuple[int, int], date] = {}
    for day in known:
        key = (day.year, day.month)
        by_month[key] = max(day, by_month.get(key, day))
    if not by_month:
        return []
    last_year, last_month = max(by_month)
    result = []
    year, month = start.year, start.month
    while (year, month) <= (last_year, last_month):
        known_day = by_month.get((year, month))
        if known_day is None:
            first_of_next = date(year + month // 12, month % 12 + 1, 1)
            known_day = first_of_next - timedelta(days=1)
        result.append(known_day)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return result

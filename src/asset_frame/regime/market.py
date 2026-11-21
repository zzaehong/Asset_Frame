"""Market-rate context shown beside the regime: yield-curve spreads, policy rate, dollar index.

Pure functions. Values are read as of each month end from the latest observation on or before it;
an observation older than the series' allowed age is treated as missing, never carried forward.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping, Sequence
from datetime import date
from statistics import fmean

CALC_VERSION = "macro_market_v1"
# Allowed age (days) of the observation used for a month end: daily series skip holidays and
# weekends, FEDFUNDS is one value per month dated on the first day of that month.
MAX_AGE_DAYS = {"T10Y3M": 10, "T10Y2Y": 10, "DTWEXBGS": 10, "FEDFUNDS": 31}
# DTWEXM (major-currencies dollar index, 1973-2019, discontinued) extends DTWEXBGS (2006~).
EXTENSION_SERIES = ("DTWEXM",)
SPLICE_OBSERVATIONS = 60
POLICY_CHANGE_MONTHS = 6
DOLLAR_CHANGE_MONTHS = 12
DOLLAR_WARNING_MONTHS = 6

Point = tuple[date, float | None]


def as_of_values(
    points: Sequence[Point], month_ends: Sequence[date], max_age_days: int
) -> list[float | None]:
    """Latest non-missing value on or before each month end, or None if too old or absent."""
    known = sorted((d, v) for d, v in points if v is not None)
    dates = [d for d, _ in known]
    values: list[float | None] = []
    for month_end in month_ends:
        index = bisect_right(dates, month_end) - 1
        recent = index >= 0 and (month_end - dates[index]).days <= max_age_days
        values.append(known[index][1] if recent else None)
    return values


def splice_level_series(old: Sequence[Point], new: Sequence[Point]) -> list[Point]:
    """`new` as is, preceded by `old` rescaled to `new`'s level.

    The scale is the mean of new/old over the first SPLICE_OBSERVATIONS dates both have. Only dates
    before the first `new` observation come from `old`. Returns `new` unchanged if nothing overlaps.
    """
    new_known = {d: v for d, v in new if v is not None}
    old_known = {d: v for d, v in old if v is not None and v}
    shared = sorted(new_known.keys() & old_known.keys())[:SPLICE_OBSERVATIONS]
    if not shared or not new_known:
        return list(new)
    scale = fmean(new_known[d] / old_known[d] for d in shared)
    first = min(new_known)
    before = [(d, v * scale) for d, v in sorted(old_known.items()) if d < first]
    return [*before, *new]


def market_context(
    series: Mapping[str, Sequence[Point]], month_ends: Sequence[date]
) -> dict | None:
    """Monthly series plus the latest readings; None when no series has any data."""
    if series.get("DTWEXM") and series.get("DTWEXBGS"):
        series = {**series, "DTWEXBGS": splice_level_series(series["DTWEXM"], series["DTWEXBGS"])}
    monthly = {
        series_id: [
            None if v is None else round(v, 4) for v in as_of_values(points, month_ends, age)
        ]
        for series_id, age in MAX_AGE_DAYS.items()
        if (points := series.get(series_id))
    }
    if not monthly:
        return None
    return {
        "calc_version": CALC_VERSION,
        "months": [month_end.isoformat() for month_end in month_ends],
        "series": monthly,
        "latest": _latest(monthly),
    }


def _latest(monthly: Mapping[str, Sequence[float | None]]) -> dict:
    def at(series_id: str, back: int = 0) -> float | None:
        values = monthly.get(series_id)
        return values[-1 - back] if values and len(values) > back else None

    fed, fed_before = at("FEDFUNDS"), at("FEDFUNDS", POLICY_CHANGE_MONTHS)
    dollar, dollar_before = at("DTWEXBGS"), at("DTWEXBGS", DOLLAR_CHANGE_MONTHS)
    dollar_6m = at("DTWEXBGS", DOLLAR_WARNING_MONTHS)
    return {
        "spread_10y3m": at("T10Y3M"),
        "spread_10y2y": at("T10Y2Y"),
        "fed_funds": fed,
        "fed_funds_change_6m": None if fed is None or fed_before is None else fed - fed_before,
        "dollar": dollar,
        "dollar_change_12m": (
            None if dollar is None or not dollar_before else dollar / dollar_before - 1
        ),
        "dollar_change_6m": None if dollar is None or not dollar_6m else dollar / dollar_6m - 1,
    }

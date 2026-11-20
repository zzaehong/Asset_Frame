"""Asset returns after a month end, grouped by the regime label known at that month end.

Pure functions. The outcome of a month end is the cumulative total return over the next `h`
months (h = 1, 3, 6, 12, 24, 36), so the label uses only information available before the
return exists.
Windows of consecutive month ends overlap, so n months give far fewer than n independent outcomes;
`independent` reports about n / h.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from statistics import fmean, median

CALC_VERSION = "regime_performance_v2"
HORIZONS = (1, 3, 6, 12, 24, 36)


def regime_performance(
    labels: Mapping[str, Sequence[str | None]],
    month_ends: Sequence[date],
    returns: Mapping[str, Mapping[date, float]],
    horizons: Sequence[int] = HORIZONS,
) -> dict:
    """{"horizons", "all", "axes": {axis: {label: cell}}}; a cell is {"months", "assets"}.

    labels[axis][i] is the label at month_ends[i] (None = unknown, skipped). A cell's asset entry
    maps each horizon (as a string) to {"n", "independent", "mean", "median", "min", "max",
    "hit_rate"} over the month ends whose whole window has a return for that ticker. "all" uses
    every month end. Returns are fractions; statistics are arithmetic over cumulative returns.
    """
    calendar = sorted({month for by_month in returns.values() for month in by_month})
    position = {month: i for i, month in enumerate(calendar)}

    def cell(indices: Sequence[int]) -> dict:
        assets: dict[str, dict] = {}
        for ticker, by_month in returns.items():
            entry = {}
            for h in horizons:
                values = [
                    v
                    for i in indices
                    if (v := _forward(by_month, calendar, position, month_ends[i], h)) is not None
                ]
                if values:
                    entry[str(h)] = {
                        "n": len(values),
                        "independent": len(values) // h,
                        "mean": round(fmean(values), 6),
                        "median": round(median(values), 6),
                        "min": round(min(values), 6),
                        "max": round(max(values), 6),
                        "hit_rate": round(sum(v > 0 for v in values) / len(values), 4),
                    }
            if entry:
                assets[ticker] = entry
        return {"months": len(indices), "assets": assets}

    axes: dict[str, dict[str, dict]] = {}
    for axis, axis_labels in labels.items():
        by_label: dict[str, list[int]] = {}
        for i, label in enumerate(axis_labels):
            if label is not None:
                by_label.setdefault(str(label), []).append(i)
        axes[axis] = {label: cell(indices) for label, indices in by_label.items()}
    return {
        "horizons": list(horizons),
        "all": cell(range(len(month_ends))),
        "axes": axes,
    }


def _forward(
    by_month: Mapping[date, float],
    calendar: Sequence[date],
    position: Mapping[date, int],
    month_end: date,
    horizon: int,
) -> float | None:
    start = position.get(month_end)
    if start is None or start + horizon >= len(calendar):
        return None
    level = 1.0
    for month in calendar[start + 1 : start + 1 + horizon]:
        if month not in by_month:
            return None
        level *= 1 + by_month[month]
    return level - 1

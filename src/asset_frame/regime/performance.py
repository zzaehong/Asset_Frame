"""Asset returns grouped by the regime that was known at the previous month end.

Pure functions. A month's return is attributed to the regime label of the month end before it,
so the label uses only information available when the return was still unknown.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from statistics import fmean

from asset_frame.regime.replay import RegimeRow

CALC_VERSION = "regime_performance_v1"
AXES = ("quadrant", "indpro_sahm", "correlation_regime")


def regime_performance(
    rows: Sequence[RegimeRow], returns: Mapping[str, Mapping[date, float]]
) -> dict[str, dict[str, dict]]:
    """{axis: {label: {"months": n, "assets": {ticker: {"mean", "hit_rate", "months"}}}}}.

    mean is the arithmetic mean monthly total return (fraction); hit_rate is the share of months
    with a positive return. A ticker missing a month is counted only over the months it has.
    """
    calendar = sorted({month for by_month in returns.values() for month in by_month})
    following = dict(zip(calendar, calendar[1:], strict=False))
    result: dict[str, dict[str, dict]] = {axis: {} for axis in AXES}
    for axis in AXES:
        by_label: dict[str, list[date]] = {}
        for row in rows:
            label = getattr(row, axis)
            if label is None or row.month_end not in following:
                continue
            by_label.setdefault(str(label), []).append(following[row.month_end])
        for label, months in by_label.items():
            assets = {}
            for ticker, by_month in returns.items():
                values = [by_month[m] for m in months if m in by_month]
                if values:
                    assets[ticker] = {
                        "mean": fmean(values),
                        "hit_rate": sum(v > 0 for v in values) / len(values),
                        "months": len(values),
                    }
            result[axis][label] = {"months": len(months), "assets": assets}
    return result

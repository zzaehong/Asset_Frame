"""Equity-market bear-market state from a total-return index, by the usual press convention.

Pure functions. Every day's state uses only prices up to that day, so a month's flag is knowable at
its month end. A bear market starts when the index closes 20% or more below its peak and ends when
it closes 20% or more above the lowest close since the start (a new bull market); the peak is then
reset to that day's level. This is a price-decline convention, not an official dating, and it says
nothing about the real economy (see regime_rules for the real-economy rule).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

CALC_VERSION = "equity_bear_v1"
BEAR_ENTRY = -0.20  # drawdown from the peak that starts a bear market
BULL_EXIT = 0.20  # rally from the bear-market low that ends it
_TOLERANCE = 1e-9  # float noise at the boundary: 80/100 - 1 is -0.19999999999999996

Level = tuple[date, float]


def bear_state(levels: Sequence[Level], month_ends: Sequence[date]) -> dict | None:
    """Per month end: drawdown at the last trading day, worst daily drawdown, bear-market flag.

    Drawdown is measured from the current peak (reset when a bear market ends). A month is flagged
    when any trading day in it was inside a bear market. Months without a trading day are None.
    Returns None when there are no levels.
    """
    if not levels:
        return None
    daily: list[tuple[date, float, bool]] = []
    peak = trough = 0.0
    bear = False
    for day, level in sorted(levels):
        if not peak:
            peak = level
        if not bear:
            peak = max(peak, level)
            if level / peak - 1 <= BEAR_ENTRY + _TOLERANCE:
                bear, trough = True, level
        else:
            trough = min(trough, level)
            if level / trough - 1 >= BULL_EXIT - _TOLERANCE:
                bear, peak = False, level
        daily.append((day, level / peak - 1, bear))
    end_drawdown: list[float | None] = []
    worst: list[float | None] = []
    flags: list[bool | None] = []
    for month_end in month_ends:
        days = [
            (dd, in_bear)
            for day, dd, in_bear in daily
            if (day.year, day.month) == (month_end.year, month_end.month) and day <= month_end
        ]
        if not days:
            end_drawdown.append(None)
            worst.append(None)
            flags.append(None)
            continue
        end_drawdown.append(round(days[-1][0], 4))
        worst.append(round(min(dd for dd, _ in days), 4))
        flags.append(any(in_bear for _, in_bear in days))
    return {
        "calc_version": CALC_VERSION,
        "entry": BEAR_ENTRY,
        "exit": BULL_EXIT,
        "month_end_drawdown": end_drawdown,
        "worst_drawdown": worst,
        "bear": flags,
    }

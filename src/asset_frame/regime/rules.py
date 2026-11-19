"""Regime rules on point-in-time macro data (rules fixed before looking at results, M2-2).

A series is a list of (observation month, release date, first-published value), observation month
being the 1st of the month. A decision at `as_of` sees only values released on or before as_of.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

CALC_VERSION = "regime_v1"
SAHM_THRESHOLD = 0.5  # percentage points, Sahm's original definition
CFNAI_MA3_THRESHOLD = -0.70  # Chicago Fed: below -0.70 after an expansion, rising recession odds
INFLATION_DIRECTION_MONTHS = 3
SERIES_FOR_RULES = ("INDPRO", "UNRATE", "CPIAUCSL", "CFNAIMA3")

Series = Sequence[tuple[date, date, float]]


def _index(month: date) -> int:
    return month.year * 12 + month.month - 1


def available(series: Series, as_of: date) -> dict[int, float]:
    """Month index -> first-published value, for values released on or before as_of."""
    return {_index(month): value for month, released, value in series if released <= as_of}


def sahm_indicator(unrate: dict[int, float]) -> float | None:
    """3-month average of the latest unemployment rate minus the minimum of the 3-month averages
    of the previous 12 months (Sahm Rule, in percentage points). None if any input month is missing.
    """
    if not unrate:
        return None
    latest = max(unrate)

    def average(month: int) -> float | None:
        values = [unrate.get(month - lag) for lag in range(3)]
        return None if None in values else sum(values) / 3  # type: ignore[arg-type]

    current = average(latest)
    prior = [average(latest - back) for back in range(1, 13)]
    if current is None or None in prior:
        return None
    return current - min(prior)  # type: ignore[type-var]


def year_over_year(values: dict[int, float], at: int | None = None) -> float | None:
    """Change of the value at month `at` (default: latest) against 12 months earlier."""
    if not values:
        return None
    month = max(values) if at is None else at
    now, before = values.get(month), values.get(month - 12)
    if now is None or before is None or before == 0:
        return None
    return now / before - 1


def inflation_direction(cpi: dict[int, float]) -> int | None:
    """+1 if CPI year-over-year is higher than INFLATION_DIRECTION_MONTHS earlier, -1 if lower."""
    if not cpi:
        return None
    latest = max(cpi)
    now = year_over_year(cpi, latest)
    before = year_over_year(cpi, latest - INFLATION_DIRECTION_MONTHS)
    if now is None or before is None or now == before:
        return None
    return 1 if now > before else -1


def rule_indpro_sahm(indpro: dict[int, float], unrate: dict[int, float]) -> bool | None:
    """Recession when industrial production is below its year-ago level AND the Sahm rule fires."""
    growth, sahm = year_over_year(indpro), sahm_indicator(unrate)
    if growth is None or sahm is None:
        return None
    return growth < 0 and sahm >= SAHM_THRESHOLD


def rule_cfnai_sahm(cfnai_ma3: dict[int, float], unrate: dict[int, float]) -> bool | None:
    """Recession when CFNAI-MA3 is below -0.70 AND the Sahm rule fires."""
    sahm = sahm_indicator(unrate)
    if not cfnai_ma3 or sahm is None:
        return None
    return cfnai_ma3[max(cfnai_ma3)] < CFNAI_MA3_THRESHOLD and sahm >= SAHM_THRESHOLD


def growth_inflation_quadrant(cfnai_ma3: dict[int, float], cpi: dict[int, float]) -> str | None:
    """Growth above/below trend (CFNAI-MA3 >= 0) x inflation rising/falling (CPI y/y direction)."""
    direction = inflation_direction(cpi)
    if not cfnai_ma3 or direction is None:
        return None
    growth = "growth_up" if cfnai_ma3[max(cfnai_ma3)] >= 0 else "growth_down"
    return f"{growth}_{'inflation_up' if direction > 0 else 'inflation_down'}"


def correlation_regime(correlation: float | None) -> str | None:
    """Sign of the trailing stock-bond correlation: positive means bonds did not hedge stocks."""
    if correlation is None:
        return None
    return "stock_bond_positive" if correlation > 0 else "stock_bond_negative"

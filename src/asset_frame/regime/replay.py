"""Month-end replay of the regime rules and their score against NBER recessions (USREC)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from asset_frame.analytics.risk import (
    WINDOW_MONTHS,
    aligned_window,
    correlation_matrix,
    trailing_months,
)
from asset_frame.regime.rules import (
    Series,
    available,
    correlation_regime,
    growth_inflation_quadrant,
    growth_inflation_quadrant_ip,
    rule_cfnai_sahm,
    rule_indpro_sahm,
    sahm_indicator,
    year_over_year,
)

REPLAY_START = date(2007, 1, 1)
RULES = ("indpro_sahm", "cfnai_sahm")


@dataclass(frozen=True, slots=True)
class RegimeRow:
    month_end: date
    sahm: float | None
    indpro_yoy: float | None
    cfnai_ma3: float | None
    indpro_sahm: bool | None
    cfnai_sahm: bool | None
    quadrant: str | None
    stock_bond_correlation: float | None
    correlation_regime: str | None
    nber_recession: bool


@dataclass(frozen=True, slots=True)
class RuleScore:
    rule: str
    months: int  # months where the rule had every input
    recession_months: int  # NBER recession months among them
    detected: int  # recession months flagged
    false_alarms: int  # flagged months outside NBER recessions
    episodes: tuple[tuple[date, int | None], ...]  # (NBER start month, months until first flag)


def replay(
    series: Mapping[str, Series],
    usrec: Mapping[date, bool],
    returns: Mapping[str, Mapping[date, float]],
    month_ends: list[date],
    start: date = REPLAY_START,
) -> tuple[RegimeRow, ...]:
    """One row per month end from `start`, using only values released by that date."""
    rows = []
    for as_of in sorted(month_ends):
        if as_of < start:
            continue
        indpro = available(series["INDPRO"], as_of)
        unrate = available(series["UNRATE"], as_of)
        cpi = available(series["CPIAUCSL"], as_of)
        cfnai = available(series["CFNAIMA3"], as_of)
        correlation = stock_bond_correlation(returns, month_ends, as_of)
        rows.append(
            RegimeRow(
                month_end=as_of,
                sahm=sahm_indicator(unrate),
                indpro_yoy=year_over_year(indpro),
                cfnai_ma3=cfnai[max(cfnai)] if cfnai else None,
                indpro_sahm=rule_indpro_sahm(indpro, unrate),
                cfnai_sahm=rule_cfnai_sahm(cfnai, unrate),
                quadrant=growth_inflation_quadrant(cfnai, cpi),
                stock_bond_correlation=correlation,
                correlation_regime=correlation_regime(correlation),
                nber_recession=usrec.get(date(as_of.year, as_of.month, 1), False),
            )
        )
    return tuple(rows)


def ip_quadrants(series: Mapping[str, Series], month_ends: Sequence[date]) -> list[str | None]:
    """INDPRO/CPI growth-inflation quadrant (`growth_inflation_quadrant_ip`) at each month end."""
    return [
        growth_inflation_quadrant_ip(
            available(series["INDPRO"], as_of), available(series["CPIAUCSL"], as_of)
        )
        for as_of in month_ends
    ]


def stock_bond_correlation(
    returns: Mapping[str, Mapping[date, float]], month_ends: list[date], as_of: date
) -> float | None:
    months = trailing_months(month_ends, as_of, WINDOW_MONTHS)
    if not months or "SPY" not in returns or "IEF" not in returns:
        return None
    window = aligned_window({t: returns[t] for t in ("SPY", "IEF")}, months)
    if len(window) < 2:
        return None
    return correlation_matrix(window)["SPY", "IEF"]


def score(rows: tuple[RegimeRow, ...], rule: str) -> RuleScore:
    scored = [(row, getattr(row, rule)) for row in rows if getattr(row, rule) is not None]
    recessions = [(row, flag) for row, flag in scored if row.nber_recession]
    episodes = []
    start = None
    first_flag: int | None = None
    count = 0
    for row, flag in scored:
        if row.nber_recession and start is None:
            start, first_flag, count = row.month_end, None, 0
        if start is not None and not row.nber_recession:
            episodes.append((start, first_flag))
            start = None
        if start is not None:
            if flag and first_flag is None:
                first_flag = count
            count += 1
    if start is not None:
        episodes.append((start, first_flag))
    return RuleScore(
        rule=rule,
        months=len(scored),
        recession_months=len(recessions),
        detected=sum(1 for _, flag in recessions if flag),
        false_alarms=sum(1 for row, flag in scored if flag and not row.nber_recession),
        episodes=tuple(episodes),
    )

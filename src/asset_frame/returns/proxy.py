"""Stand-in return history for assets younger than the period we want to study.

Pure functions. A proxy is an older fund that tracks the same market (an index mutual fund for an
ETF). Its returns fill only the months before the target's first return and are always flagged;
the months where both exist are used once to measure how well the proxy tracks the target.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from statistics import correlation, fmean

from asset_frame.returns.series import MonthlyReturn

CALC_VERSION = "proxy_v1"
MIN_OVERLAP_MONTHS = 36
# Lowest monthly-return correlation with the target over the overlap for each fidelity class, fixed
# before looking at any result. "rough" accepts any correlation: the user chose a poor stand-in
# (gold-mining fund for gold) knowingly, and the screen labels it as rough.
MIN_CORRELATION = {"index": 0.97, "close": 0.90, "rough": 0.0}


@dataclass(frozen=True, slots=True)
class OverlapStats:
    months: int
    correlation: float | None
    annual_tracking_difference: float  # mean(proxy - target) * 12, a fraction per year
    mean_abs_difference: float  # mean |proxy - target| per month, a fraction


@dataclass(frozen=True, slots=True)
class ProxyDecision:
    stats: OverlapStats | None
    used: bool
    reason: str


def overlap_stats(target: Mapping[date, float], proxy: Mapping[date, float]) -> OverlapStats | None:
    months = sorted(target.keys() & proxy.keys())
    if len(months) < 2:
        return None
    a = [proxy[m] for m in months]
    b = [target[m] for m in months]
    try:
        corr: float | None = correlation(a, b)
    except ValueError:  # a constant series has no correlation
        corr = None
    differences = [x - y for x, y in zip(a, b, strict=True)]
    return OverlapStats(
        months=len(months),
        correlation=corr,
        annual_tracking_difference=fmean(differences) * 12,
        mean_abs_difference=fmean(abs(d) for d in differences),
    )


def decide(stats: OverlapStats | None, fidelity: str) -> ProxyDecision:
    """Use the proxy only if the overlap is long enough and tracks as well as its class requires."""
    if fidelity not in MIN_CORRELATION:
        raise ValueError(f"unknown fidelity: {fidelity}")
    if stats is None or stats.months < MIN_OVERLAP_MONTHS:
        months = 0 if stats is None else stats.months
        return ProxyDecision(stats, False, f"overlap {months} months < {MIN_OVERLAP_MONTHS}")
    if stats.correlation is None:
        return ProxyDecision(stats, False, "correlation undefined")
    if stats.correlation < MIN_CORRELATION[fidelity]:
        return ProxyDecision(
            stats,
            False,
            f"correlation {stats.correlation:.3f} < {MIN_CORRELATION[fidelity]} ({fidelity})",
        )
    return ProxyDecision(stats, True, "ok")


def splice_proxy(
    target_months: Iterable[date], proxy: Iterable[MonthlyReturn], proxy_ticker: str
) -> tuple[MonthlyReturn, ...]:
    """Proxy returns for the months before the target's first return, flagged as proxy."""
    first = min(target_months, default=None)
    return tuple(
        MonthlyReturn(
            item.month_end,
            item.total_return,
            True,
            f"proxy:{proxy_ticker}:{item.source_price_version}",
        )
        for item in sorted(proxy, key=lambda item: item.month_end)
        if first is None or item.month_end < first
    )


def splice_levels(
    target: Iterable[tuple[date, float]], proxy: Iterable[tuple[date, float]]
) -> list[tuple[date, float]]:
    """Daily total-return index: the proxy before the target's first day, the target after it.

    The proxy is rescaled so both agree on the last proxy day on or before the target's first day;
    the target is then used as is (its level at its first day equals that proxy level). With no
    proxy day on or before the target's first day the target is returned unchanged.
    """
    target_levels = sorted(target)
    if not target_levels:
        return sorted(proxy)
    first_day, first_level = target_levels[0]
    earlier = [(day, level) for day, level in sorted(proxy) if day <= first_day]
    if not earlier:
        return target_levels
    scale = first_level / earlier[-1][1]
    return [(d, level * scale) for d, level in earlier if d < first_day] + target_levels


def as_floats(returns: Iterable[MonthlyReturn]) -> dict[date, float]:
    return {item.month_end: float(item.total_return) for item in returns}


def decimal_returns(returns: Mapping[date, Decimal]) -> dict[date, float]:
    return {month: float(value) for month, value in returns.items()}

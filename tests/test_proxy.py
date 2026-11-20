from datetime import date
from decimal import Decimal

import pytest

from asset_frame.returns.proxy import (
    MIN_OVERLAP_MONTHS,
    OverlapStats,
    decide,
    overlap_stats,
    splice_proxy,
)
from asset_frame.returns.series import MonthlyReturn


def month(i: int) -> date:
    return date(2000 + i // 12, i % 12 + 1, 28)


def test_overlap_stats_hand_calculation() -> None:
    target = {month(0): 0.01, month(1): 0.02, month(2): -0.01}
    proxy = {month(0): 0.02, month(1): 0.03, month(2): 0.00, month(3): 0.5}  # month 3 not shared

    stats = overlap_stats(target, proxy)

    assert stats is not None and stats.months == 3
    assert stats.annual_tracking_difference == pytest.approx(0.01 * 12)  # proxy is 1pp higher
    assert stats.mean_abs_difference == pytest.approx(0.01)
    assert stats.correlation == pytest.approx(1.0)


def test_overlap_stats_need_two_shared_months_and_survive_constants() -> None:
    assert overlap_stats({month(0): 0.01}, {month(0): 0.01}) is None
    flat = overlap_stats({month(0): 0.0, month(1): 0.0}, {month(0): 0.01, month(1): 0.02})
    assert flat is not None and flat.correlation is None


def stats(months: int, corr: float | None) -> OverlapStats:
    return OverlapStats(months, corr, 0.0, 0.0)


def test_decision_requires_enough_overlap_and_class_specific_correlation() -> None:
    assert decide(stats(MIN_OVERLAP_MONTHS, 0.98), "index").used
    assert not decide(stats(MIN_OVERLAP_MONTHS - 1, 0.99), "index").used
    assert not decide(stats(60, 0.96), "index").used
    assert decide(stats(60, 0.92), "close").used
    assert not decide(stats(60, 0.89), "close").used
    assert decide(stats(60, 0.2), "rough").used  # accepted knowingly, labelled rough
    assert not decide(stats(60, None), "rough").used
    assert not decide(None, "index").used
    with pytest.raises(ValueError):
        decide(stats(60, 0.99), "great")


def test_splice_fills_only_months_before_the_targets_first_return_and_flags_them() -> None:
    proxy = tuple(MonthlyReturn(month(i), Decimal("0.01"), False, f"s{i}") for i in range(6))

    result = splice_proxy([month(4), month(5)], proxy, "VFINX")

    assert [item.month_end for item in result] == [month(0), month(1), month(2), month(3)]
    assert all(
        item.is_proxy and item.source_price_version.startswith("proxy:VFINX:") for item in result
    )
    assert splice_proxy([], proxy, "VFINX")[-1].month_end == month(5)  # no target: all months


def test_level_splice_rescales_the_proxy_so_both_agree_at_the_targets_first_day() -> None:
    from asset_frame.returns.proxy import splice_levels

    proxy = [(date(2000, 1, 3), 10.0), (date(2000, 1, 4), 11.0), (date(2000, 1, 5), 12.0)]
    target = [(date(2000, 1, 5), 60.0), (date(2000, 1, 6), 66.0)]

    result = splice_levels(target, proxy)

    assert result == [(date(2000, 1, 3), 50.0), (date(2000, 1, 4), 55.0), *target]
    assert splice_levels(target, [(date(2000, 1, 6), 1.0)]) == target  # proxy starts too late
    assert splice_levels([], proxy) == proxy

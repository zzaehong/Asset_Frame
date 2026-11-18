from datetime import date
from decimal import Decimal

import pytest

from asset_frame.returns.series import (
    MacroPoint,
    MonthlyReturn,
    PricePoint,
    UnlinkedPriceError,
    cash_proxy_returns,
    compute_universe_returns,
    eligible_assets,
    month_ends,
    monthly_returns,
    return_anomalies,
    splice_cash,
    total_return_index,
)


def points(prices: dict[date, str], snapshot: str = "s1", fetched_at: str = "t1"):
    return [PricePoint(day, Decimal(value), snapshot, fetched_at) for day, value in prices.items()]


# Hand-calculated sample. Month-end closes 100 -> 102 -> 99.96 -> 104.958 give
# Jan +2%, Feb 99.96/102-1 = -2%, Mar 104.958/99.96-1 = +5%. Mid-month prices must not matter,
# and April is the latest (possibly partial) calendar month so it gets no return.
CALENDAR = [
    date(2023, 12, 29),
    date(2024, 1, 15),
    date(2024, 1, 31),
    date(2024, 2, 29),
    date(2024, 3, 28),
    date(2024, 4, 1),
]
SAMPLE = {
    date(2023, 12, 29): "100",
    date(2024, 1, 15): "150",
    date(2024, 1, 31): "102",
    date(2024, 2, 29): "99.96",
    date(2024, 3, 28): "104.958",
    date(2024, 4, 1): "110",
}


def test_three_month_sample_matches_hand_calculation() -> None:
    index = total_return_index(points(SAMPLE))
    ends = month_ends(CALENDAR)

    assert ends == (date(2023, 12, 29), date(2024, 1, 31), date(2024, 2, 29), date(2024, 3, 28))
    assert [point.level for point in index][:3] == [Decimal(1), Decimal("1.5"), Decimal("1.02")]
    assert [(item.month_end, item.total_return) for item in monthly_returns(index, ends)] == [
        (date(2024, 1, 31), Decimal("0.02")),
        (date(2024, 2, 29), Decimal("-0.02")),
        (date(2024, 3, 28), Decimal("0.05")),
    ]


def test_index_links_snapshots_with_different_adjustment_scales() -> None:
    older = points({date(2024, 1, 2): "10", date(2024, 1, 3): "11", date(2024, 1, 4): "12.1"})
    # A later fetch rescales the whole history (here x2) after a new dividend.
    newer = points({date(2024, 1, 4): "24.2", date(2024, 1, 5): "26.62"}, "s2", "t2")

    index = total_return_index(older + newer)

    assert [point.level for point in index] == [
        Decimal(1),
        Decimal("1.1"),
        Decimal("1.21"),
        Decimal("1.331"),
    ]
    assert [point.snapshot_id for point in index] == [None, "s1", "s1", "s2"]


def test_dates_without_a_shared_snapshot_fail_loudly() -> None:
    gap = points({date(2024, 1, 2): "10"}) + points({date(2024, 1, 3): "11"}, "s2", "t2")

    with pytest.raises(UnlinkedPriceError):
        total_return_index(gap)


def test_large_daily_moves_are_flagged_not_removed() -> None:
    index = total_return_index(
        points({date(2024, 1, 2): "100", date(2024, 1, 3): "50", date(2024, 1, 4): "60"})
    )

    assert [point.trading_date for point in return_anomalies(index)] == [date(2024, 1, 3)]
    assert index[-1].level == Decimal("0.6")


def test_cash_proxy_fills_only_months_before_the_etf() -> None:
    ends = (date(2007, 4, 30), date(2007, 5, 31), date(2007, 6, 29), date(2007, 7, 31))
    dtb3 = [
        MacroPoint(date(2007, 5, 1), Decimal("4.80"), "f1"),
        MacroPoint(date(2007, 5, 2), None, "f1"),  # FRED "." must be skipped, not read as 0
        MacroPoint(date(2007, 5, 3), Decimal("4.86"), "f1"),
        MacroPoint(date(2007, 6, 1), Decimal("4.60"), "f1"),
        MacroPoint(date(2007, 7, 2), Decimal("4.90"), "f1"),
    ]
    proxy = cash_proxy_returns(dtb3, ends)
    etf = (
        MonthlyReturn(date(2007, 7, 31), Decimal("0.004"), False, "s1"),
        MonthlyReturn(date(2007, 6, 29), Decimal("0.003"), False, "s1"),
    )

    spliced = splice_cash(etf, proxy)

    assert proxy[0].total_return == Decimal("4.83") / 100 / 12
    assert [(item.month_end, item.is_proxy) for item in spliced] == [
        (date(2007, 5, 31), True),
        (date(2007, 6, 29), False),
        (date(2007, 7, 31), False),
    ]
    assert spliced[0].source_price_version == "fred:DTB3:f1"


def test_anchor_returns_are_unchanged_by_adding_or_removing_granular_assets() -> None:
    spy = points(SAMPLE, "spy")
    lqd = points({day: str(Decimal(value) / 2) for day, value in SAMPLE.items()}, "lqd")
    vcsh = points({date(2024, 2, 29): "50", date(2024, 3, 28): "51"}, "vcsh")
    proxy = [MacroPoint(date(2024, 1, 2), Decimal("5"), "f1")]

    def anchors(prices: dict) -> bytes:
        result = compute_universe_returns(
            prices, calendar_ticker="SPY", cash_ticker="BIL", cash_proxy=proxy
        )
        return repr({t: result.returns[t] for t in ("SPY", "LQD")}).encode()

    without = anchors({"SPY": spy, "LQD": lqd})
    assert anchors({"SPY": spy, "LQD": lqd, "VCSH": vcsh}) == without
    assert anchors({"SPY": spy, "VCSH": vcsh, "LQD": lqd}) == without


def test_eligibility_needs_thirteen_months_up_to_the_decision_month() -> None:
    months = [date(2023 + (m // 12), m % 12 + 1, 28) for m in range(14)]  # 2023-01 .. 2024-02
    history = {"THIRTEEN": months[:13], "TWELVE": months[:12], "FOURTEEN": months}

    assert eligible_assets(history, date(2024, 1, 10)) == ("THIRTEEN", "FOURTEEN")
    assert eligible_assets(history, date(2023, 12, 31)) == ()

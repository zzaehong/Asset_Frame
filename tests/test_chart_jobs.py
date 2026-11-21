from datetime import date, timedelta
from decimal import Decimal

import pytest

from asset_frame.chart_jobs import (
    asset_payload,
    build_asset_chart,
    month_end_states,
    signal_performance,
    trailing_returns,
)
from asset_frame.returns.series import PricePoint

DAYS = 300
START = date(2024, 1, 1)


def series(step: float = 1.0):
    dates = [START + timedelta(days=i) for i in range(DAYS)]
    adjusted = [100.0 + step * i for i in range(DAYS)]
    points = [
        PricePoint(d, Decimal(str(a)), "s1", "t") for d, a in zip(dates, adjusted, strict=True)
    ]
    # raw close is half the adjusted close (a stand-in for later dividends/splits)
    bars = [
        (d, (a + 1) / 2, (a - 1) / 2, a / 2, 1000.0 + i)
        for i, (d, a) in enumerate(zip(dates, adjusted, strict=True))
    ]
    return points, bars, adjusted


def test_chart_series_are_aligned_and_use_the_total_return_index() -> None:
    points, bars, adjusted = series()
    chart = build_asset_chart(points, bars)
    assert chart is not None
    n = len(chart["dates"])
    assert n == DAYS and all(len(chart[k]) == n for k in ("close", "rsi", "hist", "k", "states"))
    assert chart["close"][0] == pytest.approx(1.0)  # index starts at 1
    assert chart["close"][-1] == pytest.approx(adjusted[-1] / adjusted[0])
    assert chart["ma"][20][18] is None and chart["ma"][20][19] is not None
    assert chart["states"][118] is None and chart["states"][-1] is not None
    assert chart["states"][-1]["votes"]["trend"] == 1  # a steady uptrend
    assert chart["states"][-1]["votes"]["momentum"] == 0  # flat histogram is not noise-signed


def test_high_low_are_scaled_so_the_close_sits_inside_the_range() -> None:
    points, bars, _ = series()
    chart = build_asset_chart(points, bars)
    assert 0 <= chart["k"][-1] <= 100 and chart["k"][-1] > 50


def test_payload_keeps_recent_days_and_rebases_to_100() -> None:
    points, bars, adjusted = series()
    payload = asset_payload(build_asset_chart(points, bars), recent=100)
    assert len(payload["dates"]) == 100 and payload["close"][0] == pytest.approx(100.0)
    assert payload["close"][-1] == pytest.approx(100 * adjusted[-1] / adjusted[-100], rel=1e-3)
    assert payload["now"]["date"] == payload["dates"][-1]
    assert payload["ma"]["20"][-1] is not None and payload["ma"]["240"][0] is None


def test_too_short_history_gives_none() -> None:
    points, bars, _ = series()
    assert build_asset_chart(points[:1], bars[:1]) is None


def test_month_end_state_uses_the_last_trading_day_of_the_month() -> None:
    chart = {
        "dates": [date(2024, 1, 30), date(2024, 1, 31), date(2024, 2, 28), date(2024, 2, 29)],
        "states": [
            {"state": "buy"},
            {"state": "sell"},
            {"state": "buy"},
            None,
        ],  # fmt: skip
    }
    assert month_end_states(chart) == {(2024, 1): "sell"}  # February's last day has no state


def test_signal_performance_by_state_hand_calculation() -> None:
    months = [date(2024, m, 28) for m in range(1, 9)]
    returns = dict(zip(months, [0.0, 0.10, -0.05, 0.02, 0.0, 0.03, 0.0, 0.0], strict=True))
    states = {(2024, 1): "buy", (2024, 2): "sell", (2024, 3): "buy"}
    result = signal_performance(states, returns, horizons=(1, 3))
    # buy at Jan -> next month +10%, next 3 months 1.1*0.95*1.02-1; buy at Mar -> +2%
    assert result["buy"]["months"] == 2
    assert result["buy"]["h"]["1"]["mean"] == pytest.approx((0.10 + 0.02) / 2)
    assert result["buy"]["h"]["1"]["hit_rate"] == 1.0
    assert result["sell"]["h"]["1"]["mean"] == pytest.approx(-0.05)
    assert result["buy"]["h"]["3"]["n"] == 2
    assert result["all"]["months"] == 3 and result["all"]["h"]["1"]["n"] == 3


def test_trailing_returns_use_trading_days_and_need_enough_history() -> None:
    close = [100.0, 110.0, 121.0, 133.1]
    out = trailing_returns(close, {"1": 1, "3": 3, "4": 4})
    assert out["1"] == pytest.approx(0.10) and out["3"] == pytest.approx(0.331)
    assert out["4"] is None  # needs five prices


def test_payload_carries_trailing_returns() -> None:
    points, bars, adjusted = series()
    payload = asset_payload(build_asset_chart(points, bars))
    assert payload["trailing"]["1M"] == pytest.approx(adjusted[-1] / adjusted[-22] - 1, abs=1e-4)
    assert payload["trailing"]["12M"] is not None

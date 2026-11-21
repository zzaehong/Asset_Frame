from asset_frame.analytics.chart_signal import classify, daily_states


def one(close, ma60, ma120, hist, rsi, k=(None, None), d=(None, None)):
    """Evaluate the last of two days; k and d are (previous, current)."""
    return daily_states(
        [close, close], [ma60, ma60], [ma120, ma120], [hist, hist], [rsi, rsi], list(k), list(d)
    )[-1]


def test_classification_thresholds() -> None:
    assert [classify(t) for t in (4, 2, 1, 0, -1, -2, -4)] == [
        "buy", "buy", "neutral", "neutral", "neutral", "sell", "sell",
    ]  # fmt: skip


def test_trend_and_momentum_follow_the_price() -> None:
    up = one(110, 105, 100, 0.5, 50)
    assert up["votes"] == {"trend": 1, "momentum": 1, "rsi": 0, "stochastic": 0}
    assert up["state"] == "buy" and not up["conflict"]
    down = one(90, 95, 100, -0.5, 50)
    assert down["state"] == "sell" and down["total"] == -2


def test_rsi_is_counter_trend_and_flags_a_conflict() -> None:
    overheated = one(110, 105, 100, 0.5, 75)  # +1 +1 -1
    assert overheated["total"] == 1 and overheated["state"] == "neutral" and overheated["conflict"]
    assert one(90, 95, 100, -0.5, 25)["votes"]["rsi"] == 1


def test_mixed_trend_votes_zero() -> None:
    assert one(110, 95, 100, 0.0, 50)["votes"]["trend"] == 0  # close above, MA60 below MA120


def test_stochastic_cross_only_below_20_or_above_80() -> None:
    low_cross = daily_states(
        [1.0] * 3, [1.0] * 3, [1.0] * 3, [1.0] * 3, [50.0] * 3,
        [None, 10.0, 15.0], [None, 12.0, 14.0],
    )  # fmt: skip
    assert low_cross[2]["votes"]["stochastic"] == 1  # K 10<=D 12 then K 15>D 14, K<20
    mid_cross = daily_states(
        [1.0] * 3, [1.0] * 3, [1.0] * 3, [1.0] * 3, [50.0] * 3,
        [None, 40.0, 50.0], [None, 45.0, 48.0],
    )  # fmt: skip
    assert mid_cross[2]["votes"]["stochastic"] == 0
    high_cross = daily_states(
        [1.0] * 3, [1.0] * 3, [1.0] * 3, [1.0] * 3, [50.0] * 3,
        [None, 90.0, 85.0], [None, 88.0, 86.0],
    )  # fmt: skip
    assert high_cross[2]["votes"]["stochastic"] == -1


def test_a_cross_persists_five_days_then_expires() -> None:
    k = [None, 10.0, 15.0] + [30.0] * 6
    d = [None, 12.0, 14.0] + [20.0] * 6
    n = len(k)
    out = daily_states([1.0] * n, [1.0] * n, [1.0] * n, [1.0] * n, [50.0] * n, k, d)
    assert out[2]["votes"]["stochastic"] == 1
    assert out[6]["votes"]["stochastic"] == 1  # 4 days later
    assert out[8]["votes"]["stochastic"] == 0  # 6 days later


def test_state_is_none_without_ma120_or_macd() -> None:
    assert one(110, 105, None, 0.5, 50) is None
    assert one(110, 105, 100, None, 50) is None


def test_histogram_noise_around_zero_is_not_a_vote() -> None:
    assert one(100, 105, 100, -1e-12, 50)["votes"]["momentum"] == 0

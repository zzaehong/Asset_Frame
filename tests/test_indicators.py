import pytest

from asset_frame.analytics.indicators import ema, macd, rsi, sma, stochastic, volume_ratio


def test_sma_is_none_until_the_window_fills() -> None:
    assert sma([1, 2, 3, 4, 5], 3) == [None, None, 2.0, 3.0, 4.0]


def test_ema_is_seeded_with_the_sma_and_follows_the_recursion() -> None:
    out = ema([1, 2, 3, 4, 5], 3)  # alpha 0.5, seed (1+2+3)/3 = 2
    assert out[:2] == [None, None]
    assert out[2:] == pytest.approx([2.0, 3.0, 4.0])


def test_rsi_extremes_and_flat() -> None:
    assert rsi([float(i) for i in range(1, 30)])[-1] == 100.0
    assert rsi([float(i) for i in range(30, 1, -1)])[-1] == pytest.approx(0.0)
    assert rsi([5.0] * 30)[-1] == 50.0
    assert rsi([1.0, 2.0]) == [None, None]


def test_rsi_wilder_hand_calculation() -> None:
    # n = 2: changes +1, -1 give avg gain .5 and avg loss .5 (RSI 50);
    # then +2: gain (.5 + 2) / 2 = 1.25, loss .5 / 2 = .25
    values = [10.0, 11.0, 10.0, 12.0]
    out = rsi(values, 2)
    assert out[2] == pytest.approx(50.0)
    assert out[3] == pytest.approx(100 - 100 / (1 + 1.25 / 0.25))


def test_macd_of_a_constant_series_is_zero_and_needs_history() -> None:
    line, signal, histogram = macd([100.0] * 60)
    assert line[24] is None and line[25] == pytest.approx(0.0)
    assert signal[-1] == pytest.approx(0.0) and histogram[-1] == pytest.approx(0.0)
    assert macd([1.0] * 10)[0] == [None] * 10


def test_macd_is_positive_in_an_uptrend() -> None:
    line, _, _ = macd([100.0 + i for i in range(80)])
    assert line[-1] > 0


def test_stochastic_top_of_range_is_100_and_flat_is_50() -> None:
    high = [float(i) + 1 for i in range(30)]
    low = [float(i) - 1 for i in range(30)]
    close = [float(i) + 1 for i in range(30)]  # closes at the high
    k, d = stochastic(high, low, close)
    assert k[-1] > 90 and d[-1] > 90
    assert k[14] is None and k[15] is not None  # raw from day 14, then SMA3
    flat = [5.0] * 30
    assert stochastic(flat, flat, flat)[0][-1] == 50.0


def test_stochastic_hand_calculation() -> None:
    # n=2, smoothing 1: raw %K = 100 (close - min low)/(max high - min low)
    k, d = stochastic([2, 4, 3], [1, 2, 1], [2, 3, 2], n=2, smooth_k=1, smooth_d=1)
    assert k == [
        None,
        pytest.approx(100 * (3 - 1) / (4 - 1)),
        pytest.approx(100 * (2 - 1) / (4 - 1)),
    ]


def test_volume_ratio_against_the_trailing_mean() -> None:
    out = volume_ratio([10.0] * 19 + [30.0], 20)
    assert out[:19] == [None] * 19
    assert out[19] == pytest.approx(30 / 11)
    assert volume_ratio([0.0] * 20)[-1] is None

"""Chart indicators on daily series. Pure functions; None marks "not enough history".

Price basis: callers pass the total-return (adjusted) close and high/low scaled by
adjusted_close / raw close, so dividends and splits do not create fake gaps.
Conventions: SMA = plain mean of the last n values. EMA alpha = 2 / (n + 1), seeded with the SMA of
the first n values. RSI uses Wilder smoothing (alpha = 1 / n) seeded with the mean of the first n
changes; flat prices (no gain and no loss) give 50. MACD = EMA(12) - EMA(26), signal = EMA(9) of
MACD, histogram = MACD - signal. Slow stochastic (14, 3, 3): raw %K = 100 (close - lowest low) /
(highest high - lowest low) over 14 days (50 when the range is zero), %K = SMA3 of raw %K,
%D = SMA3 of %K. Volume ratio = volume / mean of the last 20 volumes (today included).
"""

from __future__ import annotations

from collections.abc import Sequence

CALC_VERSION = "indicators_v1"
MA_WINDOWS = (20, 60, 120, 240)


def sma(values: Sequence[float | None], n: int) -> list[float | None]:
    out: list[float | None] = []
    for i in range(len(values)):
        window = values[i - n + 1 : i + 1] if i >= n - 1 else []
        out.append(sum(window) / n if len(window) == n and None not in window else None)  # type: ignore[arg-type]
    return out


def ema(values: Sequence[float | None], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    first = next((i for i, v in enumerate(values) if v is not None), None)
    if first is None or len(values) - first < n:
        return out
    seed = first + n - 1
    previous = sum(values[first : seed + 1]) / n  # type: ignore[arg-type]
    out[seed] = previous
    alpha = 2 / (n + 1)
    for i in range(seed + 1, len(values)):
        previous = alpha * values[i] + (1 - alpha) * previous  # type: ignore[operator]
        out[i] = previous
    return out


def rsi(values: Sequence[float], n: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) <= n:
        return out
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    gain = sum(max(c, 0) for c in changes[:n]) / n
    loss = sum(max(-c, 0) for c in changes[:n]) / n

    def value() -> float:
        if gain == 0 and loss == 0:
            return 50.0
        return 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)

    out[n] = value()
    for i in range(n + 1, len(values)):
        change = changes[i - 1]
        gain = (gain * (n - 1) + max(change, 0)) / n
        loss = (loss * (n - 1) + max(-change, 0)) / n
        out[i] = value()
    return out


def macd(
    values: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    fast_line, slow_line = ema(values, fast), ema(values, slow)
    line = [
        None if f is None or s is None else f - s for f, s in zip(fast_line, slow_line, strict=True)
    ]
    signal_line = ema(line, signal)
    histogram = [
        None if m is None or s is None else m - s for m, s in zip(line, signal_line, strict=True)
    ]
    return line, signal_line, histogram


def stochastic(
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    n: int = 14,
    smooth_k: int = 3,
    smooth_d: int = 3,
) -> tuple[list[float | None], list[float | None]]:
    raw: list[float | None] = []
    for i in range(len(close)):
        if i < n - 1:
            raw.append(None)
            continue
        highest, lowest = max(high[i - n + 1 : i + 1]), min(low[i - n + 1 : i + 1])
        raw.append(50.0 if highest == lowest else 100 * (close[i] - lowest) / (highest - lowest))
    k = sma(raw, smooth_k)
    return k, sma(k, smooth_d)


def volume_ratio(volume: Sequence[float], n: int = 20) -> list[float | None]:
    average = sma(volume, n)
    return [None if a is None or a == 0 else v / a for v, a in zip(volume, average, strict=True)]

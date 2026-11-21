"""Chart rule signal: four indicator votes added up. Rule fixed before any result was seen.

Votes (each +1, -1 or 0):
  trend      +1 close > MA120 and MA60 > MA120; -1 close < MA120 and MA60 < MA120
  momentum   +1 MACD histogram > 0; -1 < 0 (|histogram| <= 1e-9 x close counts as 0, float noise)
  rsi        +1 RSI <= 30 (oversold); -1 RSI >= 70 (overbought)
  stochastic +1 %K crossed above %D while %K < 20; -1 %K crossed below %D while %K > 80;
             a cross counts for the next STOCH_PERSIST trading days (a cross lasts one day, which
             would almost never be the month end) and the latest cross in that window wins.
Total >= +2 is "buy" (매수 우위), <= -2 is "sell" (매도 우위), otherwise "neutral" (중립). The state
is None until MA120 and the MACD histogram exist. A missing RSI or stochastic value votes 0.
Volume is shown as a ratio to its 20-day mean and does not vote. `conflict` flags a day on which
the votes point both ways (RSI and stochastic are counter-trend, trend and momentum follow it).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypedDict

CALC_VERSION = "chart_signal_v1"
BUY_AT, SELL_AT = 2, -2
OVERSOLD, OVERBOUGHT = 30, 70
STOCH_LOW, STOCH_HIGH = 20, 80
STOCH_PERSIST = 5
FLAT = 1e-9


class State(TypedDict):
    votes: dict[str, int]
    total: int
    state: str
    conflict: bool


def _stochastic_vote(k: Sequence[float | None], d: Sequence[float | None], i: int) -> int:
    for j in range(i, max(i - STOCH_PERSIST, 0) - 1, -1):
        if j == 0 or None in (k[j], d[j], k[j - 1], d[j - 1]):
            continue
        if k[j - 1] <= d[j - 1] and k[j] > d[j] and k[j] < STOCH_LOW:  # type: ignore[operator]
            return 1
        if k[j - 1] >= d[j - 1] and k[j] < d[j] and k[j] > STOCH_HIGH:  # type: ignore[operator]
            return -1
    return 0


def classify(total: int) -> str:
    return "buy" if total >= BUY_AT else "sell" if total <= SELL_AT else "neutral"


def daily_states(
    close: Sequence[float],
    ma60: Sequence[float | None],
    ma120: Sequence[float | None],
    histogram: Sequence[float | None],
    rsi: Sequence[float | None],
    k: Sequence[float | None],
    d: Sequence[float | None],
) -> list[State | None]:
    out: list[State | None] = []
    for i in range(len(close)):
        if ma60[i] is None or ma120[i] is None or histogram[i] is None:
            out.append(None)
            continue
        trend = (
            1
            if close[i] > ma120[i] and ma60[i] > ma120[i]
            # type: ignore[operator]
            else (
                -1 if close[i] < ma120[i] and ma60[i] < ma120[i] else 0  # type: ignore[operator]
            )
        )
        h = histogram[i]
        momentum = 0 if abs(h) <= FLAT * close[i] else 1 if h > 0 else -1  # type: ignore[operator]
        r = rsi[i]
        votes = {
            "trend": trend,
            "momentum": momentum,
            "rsi": 0 if r is None else 1 if r <= OVERSOLD else -1 if r >= OVERBOUGHT else 0,
            "stochastic": _stochastic_vote(k, d, i),
        }
        total = sum(votes.values())
        values = set(votes.values())
        out.append(
            {
                "votes": votes,
                "total": total,
                "state": classify(total),
                "conflict": 1 in values and -1 in values,
            }
        )
    return out

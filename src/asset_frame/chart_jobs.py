"""Per-ETF daily chart data: indicators, rule signal and how each signal state did afterwards.

Indicators are computed on the whole history; the payload keeps the last RECENT_DAYS trading days.
Price basis: total-return index (adjusted close, chained inside one snapshot), high/low scaled by
index / raw close, volume raw. See analytics.indicators and analytics.chart_signal.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from uuid import UUID

from asset_frame.analytics.chart_signal import CALC_VERSION as SIGNAL_VERSION
from asset_frame.analytics.chart_signal import State, daily_states
from asset_frame.analytics.indicators import (
    CALC_VERSION as INDICATOR_VERSION,
)
from asset_frame.analytics.indicators import (
    MA_WINDOWS,
    macd,
    rsi,
    sma,
    stochastic,
    volume_ratio,
)
from asset_frame.regime.performance import regime_performance
from asset_frame.returns.series import PricePoint, total_return_index

RECENT_DAYS = 504
SIGNAL_HORIZONS = (1, 3, 6)
# Trading days behind the heatmap columns: about 1, 3, 6 and 12 months.
TRAILING_DAYS = {"1M": 21, "3M": 63, "6M": 126, "12M": 252}
STATES = ("buy", "neutral", "sell")


def build_asset_chart(
    points: Sequence[PricePoint],
    bars: Sequence[tuple[date, float, float, float, float]],
) -> dict | None:
    """Full-history indicator series plus daily rule states for one asset, or None if too short."""
    level = {p.trading_date: float(p.level) for p in total_return_index(points)}
    rows = [bar for bar in bars if bar[0] in level and bar[3] > 0]
    if len(rows) < 2:
        return None
    dates = [r[0] for r in rows]
    close = [level[r[0]] for r in rows]
    scale = [level[r[0]] / r[3] for r in rows]
    high = [r[1] * s for r, s in zip(rows, scale, strict=True)]
    low = [r[2] * s for r, s in zip(rows, scale, strict=True)]
    volume = [r[4] for r in rows]
    line, signal, histogram = macd(close)
    k, d = stochastic(high, low, close)
    averages = {n: sma(close, n) for n in MA_WINDOWS}
    rsi_line = rsi(close)
    return {
        "dates": dates,
        "close": close,
        "ma": averages,
        "rsi": rsi_line,
        "macd": line,
        "signal": signal,
        "hist": histogram,
        "k": k,
        "d": d,
        "volume": volume,
        "volume_ratio": volume_ratio(volume),
        "states": daily_states(close, averages[60], averages[120], histogram, rsi_line, k, d),
    }


def trailing_returns(close: Sequence[float], days: Mapping[str, int] = TRAILING_DAYS) -> dict:
    """Total return over the last `n` trading days (None if the history is shorter than n + 1)."""
    last = close[-1]
    return {
        name: (last / close[-1 - n] - 1 if len(close) > n else None) for name, n in days.items()
    }


def _round(values: Sequence[float | None], digits: int = 4) -> list[float | None]:
    return [None if v is None else round(v, digits) for v in values]


def asset_payload(chart: dict, recent: int = RECENT_DAYS) -> dict:
    """The last `recent` days, prices rebased to 100 at the first shown day."""
    start = max(0, len(chart["dates"]) - recent)
    base = chart["close"][start] / 100
    cut = slice(start, None)
    states: list[State | None] = chart["states"][cut]
    last = chart["states"][-1]
    return {
        "dates": [d.isoformat() for d in chart["dates"][cut]],
        "close": _round([v / base for v in chart["close"][cut]], 3),
        "ma": {
            str(n): _round([None if v is None else v / base for v in chart["ma"][n][cut]], 3)
            for n in MA_WINDOWS
        },  # fmt: skip
        "rsi": _round(chart["rsi"][cut], 2),
        "macd": _round([None if v is None else v / base for v in chart["macd"][cut]], 4),
        "signal": _round([None if v is None else v / base for v in chart["signal"][cut]], 4),
        "hist": _round([None if v is None else v / base for v in chart["hist"][cut]], 4),
        "k": _round(chart["k"][cut], 1),
        "d": _round(chart["d"][cut], 1),
        "volume": [int(v) for v in chart["volume"][cut]],
        "volume_ratio": _round(chart["volume_ratio"][cut], 2),
        "trailing": {
            k: None if v is None else round(v, 4)
            for k, v in trailing_returns(chart["close"]).items()
        },
        "state": [None if s is None else s["state"] for s in states],
        "now": None if last is None else {**last, "date": chart["dates"][-1].isoformat()},
    }


def month_end_states(chart: dict) -> dict[tuple[int, int], str]:
    """The rule state on the last trading day of each month (months without a state skipped)."""
    out: dict[tuple[int, int], str] = {}
    for day, state in zip(chart["dates"], chart["states"], strict=True):
        if state is not None:
            out[(day.year, day.month)] = state["state"]
        elif (day.year, day.month) in out:
            del out[(day.year, day.month)]
    return out


def signal_performance(
    states: Mapping[tuple[int, int], str],
    returns: Mapping[date, float],
    horizons: Sequence[int] = SIGNAL_HORIZONS,
) -> dict[str, dict]:
    """{state | "all": {"months": n, "h": {horizon: stats}}} for one asset's month-end states."""
    calendar = sorted(returns)
    by_month = {(m.year, m.month): m for m in calendar}
    month_ends = [by_month[key] for key in sorted(states) if key in by_month]
    if not month_ends:
        return {}
    labels = [states[(m.year, m.month)] for m in month_ends]
    result = regime_performance({"signal": labels}, month_ends, {"x": returns}, horizons)
    cells = {**result["axes"]["signal"], "all": result["all"]}  # "all": every month with a state
    return {
        label: {"months": cell["months"], "h": cell["assets"].get("x", {})}
        for label, cell in cells.items()
    }


def build_chart_data(
    tickers: Sequence[str],
    ids: Mapping[str, UUID],
    store,
    returns: Mapping[str, Mapping[date, float]],
) -> dict:
    """{"assets": {ticker: payload}, "performance": {ticker: ...}, versions}; skips short assets."""
    assets, performance = {}, {}
    for ticker in tickers:
        chart = build_asset_chart(store.price_points(ids[ticker]), store.daily_bars(ids[ticker]))
        if chart is None:
            continue
        assets[ticker] = asset_payload(chart)
        if ticker in returns:
            performance[ticker] = signal_performance(month_end_states(chart), returns[ticker])
    return {
        "assets": assets,
        "performance": performance,
        "calc_version": SIGNAL_VERSION,
        "indicator_version": INDICATOR_VERSION,
    }

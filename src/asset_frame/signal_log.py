"""Ledger records of the chart and macro rule signals, and their scoring.

An observation is one entry per month end: every asset's chart state and votes plus the macro
suggestion (strong / weak assets and the three warnings). Entries are append-only (ADR-0007).
Scoring happens once the outcome is known, as separate entries:
  chart  3 months after: a "buy" is a hit when the asset's cumulative 3-month total return is > 0,
         a "sell" when it is < 0. "neutral" is not scored. Hit rates are per asset-month and the
         assets overlap, so the independent sample is the number of observed months, not assets.
  macro  6 months after: mean 6-month return of the strong assets minus that of the weak ones
         (the spread). Positive means the suggestion pointed the right way.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date

from asset_frame.analytics.chart_signal import CALC_VERSION as CHART_VERSION
from asset_frame.prediction.scoring import realized_returns
from asset_frame.regime.actions import CALC_VERSION as MACRO_VERSION
from asset_frame.storage.ledger import LedgerStore

CALC_VERSION = "signal_log_v1"
OBSERVATION = "signal_observation"
SCORE = "signal_score"
CHART_HORIZON, MACRO_HORIZON = 3, 6


def state_on(chart: Mapping, month_end: date) -> dict | None:
    """The chart rule state on the last trading day on or before `month_end`."""
    found = None
    for day, state in zip(chart["dates"], chart["states"], strict=True):
        if day > month_end:
            break
        found = state
    return found


def macro_snapshot(regime: Mapping, axis: str = "quadrant") -> dict:
    """The latest month's macro suggestion from the dashboard's regime payload."""
    label = regime["rows"][-1][axis]
    cell = regime["actions"]["axes"].get(axis, {}).get(label) if label else None
    return {
        "axis": axis,
        "label": label,
        "strong": [e["ticker"] for e in cell["strong"]] if cell else [],
        "weak": [e["ticker"] for e in cell["weak"]] if cell else [],
        "warnings": {w["key"]: w["state"] for w in regime["actions"]["warnings"]},
    }


def record_signals(
    ledger: LedgerStore,
    month_end: date,
    charts: Mapping[str, Mapping],
    macro: Mapping | None,
) -> bool:
    """Append the observation for `month_end`; False if that month is already in the ledger."""
    chart_states = {}
    for ticker, chart in charts.items():
        state = state_on(chart, month_end)
        if state is not None:
            chart_states[ticker] = {k: state[k] for k in ("state", "total", "votes")}
    payload = {
        "calc_version": CALC_VERSION,
        "chart_version": CHART_VERSION,
        "macro_version": MACRO_VERSION,
        "month_end": month_end.isoformat(),
        "chart": chart_states,
        "macro": macro,
    }
    key = f"{OBSERVATION}:{month_end}:{CALC_VERSION}"
    return ledger.append(OBSERVATION, payload, key=key) is not None


def _after(month_ends: Sequence[date], as_of: date, months: int) -> tuple[date, ...] | None:
    later = sorted(m for m in month_ends if m > as_of)
    return tuple(later[:months]) if len(later) >= months else None


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def score_signals(
    ledger: LedgerStore, returns: Mapping[str, Mapping[date, float]], month_ends: Sequence[date]
) -> int:
    """Append the missing chart / macro scores whose horizon is complete; returns how many."""
    entries = ledger.entries()
    done = {
        (p["observation_seq"], p["scope"])
        for e in entries
        if e.entry_type == SCORE and (p := json.loads(e.payload))
    }
    count = 0
    for entry in entries:
        if entry.entry_type != OBSERVATION:
            continue
        observed = json.loads(entry.payload)
        as_of = date.fromisoformat(observed["month_end"])
        chart_months = _after(month_ends, as_of, CHART_HORIZON)
        if chart_months and (entry.seq, "chart") not in done:
            realized = realized_returns(returns, list(observed["chart"]), chart_months)
            buys = [
                realized[t]
                for t, s in observed["chart"].items()
                if s["state"] == "buy" and t in realized
            ]
            sells = [
                realized[t]
                for t, s in observed["chart"].items()
                if s["state"] == "sell" and t in realized
            ]
            body = {
                "buy": {"n": len(buys), "hits": sum(r > 0 for r in buys), "mean": _mean(buys)},
                "sell": {"n": len(sells), "hits": sum(r < 0 for r in sells), "mean": _mean(sells)},
            }
            count += _append(ledger, entry.seq, "chart", observed, chart_months[-1], body)
        macro_months = _after(month_ends, as_of, MACRO_HORIZON)
        macro = observed.get("macro")
        if macro_months and macro and (entry.seq, "macro") not in done:
            realized = realized_returns(returns, [*macro["strong"], *macro["weak"]], macro_months)
            strong = [realized[t] for t in macro["strong"] if t in realized]
            weak = [realized[t] for t in macro["weak"] if t in realized]
            s, w = _mean(strong), _mean(weak)
            body = {
                "strong_mean": s,
                "weak_mean": w,
                "spread": None if s is None or w is None else s - w,
            }
            count += _append(ledger, entry.seq, "macro", observed, macro_months[-1], body)
    return count


def _append(
    ledger: LedgerStore, seq: int, scope: str, observed: Mapping, end: date, body: dict
) -> int:
    payload = {
        "calc_version": CALC_VERSION,
        "observation_seq": seq,
        "scope": scope,
        "as_of": observed["month_end"],
        "horizon_end": end.isoformat(),
        **body,
    }
    return int(ledger.append(SCORE, payload, key=f"{SCORE}:{seq}:{scope}") is not None)


def scoreboard(ledger: LedgerStore) -> dict:
    """Totals over every scored observation, with the number of months behind them."""
    chart = {"months": 0, "buy_n": 0, "buy_hits": 0, "sell_n": 0, "sell_hits": 0}
    spreads: list[float] = []
    for e in ledger.entries():
        if e.entry_type != SCORE:
            continue
        p = json.loads(e.payload)
        if p["scope"] == "chart":
            chart["months"] += 1
            for side in ("buy", "sell"):
                chart[f"{side}_n"] += p[side]["n"]
                chart[f"{side}_hits"] += p[side]["hits"]
        elif p["spread"] is not None:
            spreads.append(p["spread"])
    return {"chart": chart, "macro": {"months": len(spreads), "mean_spread": _mean(spreads)}}

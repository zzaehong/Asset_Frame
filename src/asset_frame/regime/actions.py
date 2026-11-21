"""Macro judgment: which assets were relatively strong or weak in each growth x inflation state,
plus three market warnings. Rules fixed before any result was seen (calc version macro_action_v1).

Strong / weak: among `tickers` with at least MIN_INDEPENDENT independent 6-month outcomes in that
state (independent = months // 6), rank by the mean cumulative 6-month total return. The top and
bottom min(TOP, eligible // 2) are "strong" and "weak". Fewer than MIN_ELIGIBLE eligible assets
means the state has too little history and no suggestion is made.
Warnings (shown beside the suggestion, they never change it):
  curve   10y-3m spread < 0 (inverted)
  policy  policy rate up by at least 1.0 percentage point over 6 months
  dollar  broad dollar index up by at least 5% over 6 months
Data missing for a warning is "na", never "ok".
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

CALC_VERSION = "macro_action_v1"
HORIZON = "6"
MIN_INDEPENDENT = 5
MIN_ELIGIBLE = 4
TOP = 3
CURVE_LIMIT = 0.0
POLICY_RISE = 1.0
DOLLAR_RISE = 0.05


def _entry(ticker: str, stats: Mapping) -> dict:
    return {
        "ticker": ticker,
        "mean": stats["mean"],
        "hit_rate": stats["hit_rate"],
        "n": stats["n"],
        "independent": stats["independent"],
    }


def quadrant_actions(performance: Mapping, axis: str, tickers: Sequence[str]) -> dict[str, dict]:
    """{label: {"eligible", "months", "strong", "weak", "baseline"}} for one performance axis."""
    cells = performance.get("axes", {}).get(axis, {})
    baseline = performance.get("all", {}).get("assets", {})
    out = {}
    for label, cell in cells.items():
        found = [
            _entry(t, cell["assets"][t][HORIZON])
            for t in tickers
            if HORIZON in cell["assets"].get(t, {})
            and cell["assets"][t][HORIZON]["independent"] >= MIN_INDEPENDENT
        ]
        found.sort(key=lambda e: (-e["mean"], e["ticker"]))
        take = min(TOP, len(found) // 2) if len(found) >= MIN_ELIGIBLE else 0
        out[label] = {
            "months": cell["months"],
            "eligible": len(found),
            "strong": found[:take],
            "weak": found[::-1][:take],
            "baseline": {
                t: baseline[t][HORIZON]["mean"]
                for t in [e["ticker"] for e in found[:take] + found[::-1][:take]]
                if HORIZON in baseline.get(t, {})
            },
        }
    return out


def warnings(latest: Mapping | None) -> list[dict]:
    """Curve, policy-rate and dollar warnings from `macro_market` latest readings."""
    latest = latest or {}
    spread = latest.get("spread_10y3m")
    policy = latest.get("fed_funds_change_6m")
    dollar = latest.get("dollar_change_6m")

    def state(value: float | None, active: bool) -> str:
        return "na" if value is None else "warn" if active else "ok"

    return [
        {
            "key": "curve",
            "name": "수익률 곡선",
            "state": state(spread, spread is not None and spread < CURVE_LIMIT),
            "value": spread,
        },
        {
            "key": "policy",
            "name": "정책금리",
            "state": state(policy, policy is not None and policy >= POLICY_RISE),
            "value": policy,
        },
        {
            "key": "dollar",
            "name": "달러지수",
            "state": state(dollar, dollar is not None and dollar >= DOLLAR_RISE),
            "value": dollar,
        },
    ]


def macro_actions(
    performance: Mapping, axes: Sequence[str], tickers: Sequence[str], latest: Mapping | None
) -> dict:
    return {
        "calc_version": CALC_VERSION,
        "horizon": int(HORIZON),
        "axes": {axis: quadrant_actions(performance, axis, tickers) for axis in axes},
        "warnings": warnings(latest),
    }

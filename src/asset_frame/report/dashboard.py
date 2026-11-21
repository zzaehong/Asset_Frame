"""Offline web dashboard: one self-contained HTML file with the computed results embedded.

All numbers are computed here in Python; the page only filters and draws them. The file loads
nothing from the network, so it opens from disk without a server.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from asset_frame.backtest.engine import CALC_VERSION as BACKTEST_CALC_VERSION
from asset_frame.backtest.engine import RULES
from asset_frame.backtest.jobs import CRISIS_WINDOWS, BacktestResult, window_stat
from asset_frame.backtest.strategies import Strategy
from asset_frame.regime.equity import bear_state
from asset_frame.regime.market import market_context
from asset_frame.regime.performance import CALC_VERSION as REGIME_PERFORMANCE_VERSION
from asset_frame.regime.performance import regime_performance
from asset_frame.regime.replay import RegimeRow
from asset_frame.universe import UniverseAsset
from asset_frame.universe_jobs import Analysis

BENCHMARKS = ("bench_spy", "bench_6040")
TEMPLATE_PATH = Path(__file__).with_name("dashboard.html")
ENGINE_PATH = Path(__file__).with_name("dashboard_engine.js")
_DATA_PLACEHOLDER = "/*__DATA__*/null"
_ENGINE_PLACEHOLDER = "/*__ENGINE__*/"


@dataclass(frozen=True, slots=True)
class LongContext:
    """Regime inputs over the long history: proxy-extended returns, macro rows from 1962."""

    rows: Sequence[RegimeRow]
    quadrants_ip: Sequence[str | None]
    returns: Mapping[str, Mapping[date, float]]
    equity_levels: Sequence[tuple[date, float]]
    macro_points: Mapping[str, Sequence[tuple[date, float | None]]]


def build_payload(
    result: BacktestResult,
    analysis: Analysis,
    *,
    universe: Sequence[UniverseAsset],
    strategies: Sequence[Strategy],
    returns: Mapping[str, Mapping[date, float]],
    proxy_months: Mapping[str, Sequence[date]],
    cash_ticker: str,
    generated_on: date,
    regime_rows: Sequence[RegimeRow] = (),
    macro_points: Mapping[str, Sequence[tuple[date, float | None]]] | None = None,
    equity_levels: Sequence[tuple[date, float]] = (),
    quadrants_ip: Sequence[str | None] | None = None,
    long_context: LongContext | None = None,
    proxies: Sequence[dict] = (),
    dividends: Mapping[str, dict] | None = None,
    charts: Mapping[str, dict] | None = None,
) -> dict:
    strategy_ids = [s.id for s in strategies]
    anchors = [a.ticker for a in universe if a.level == 1 and a.role == "anchor"]
    rows = {(row.strategy, row.rule): row for row in result.rows}
    performance: dict[str, dict] = {rule: {} for rule in RULES}
    for (strategy, rule), row in rows.items():
        p = row.performance
        entry = {
            "cagr": p.cagr,
            "volatility": p.volatility,
            "sharpe": p.sharpe,
            "sortino": p.sortino,
            "calmar": p.calmar,
            "max_drawdown": p.max_drawdown,
            "turnover": row.mean_turnover,
            "versus": {},
        }
        for name in BENCHMARKS:
            relative, bench = row.versus.get(name), rows.get((name, rule))
            if relative is None or bench is None or strategy == name:
                continue
            bench_p = bench.performance
            entry["versus"][name] = {
                "excess_cagr": relative.excess_cagr,
                "information_ratio": relative.information_ratio,
                "better_sharpe": p.sharpe is not None
                and bench_p.sharpe is not None
                and p.sharpe > bench_p.sharpe,
                "smaller_drawdown": p.max_drawdown > bench_p.max_drawdown,
            }
        performance[rule][strategy] = entry

    wealth: dict[str, dict] = {rule: {} for rule in RULES}
    crisis: dict[str, dict] = {rule: {} for rule in RULES}
    average_weights: dict[str, dict] = {rule: {} for rule in RULES}
    for strategy in strategy_ids:
        for rule in RULES:
            by_month = {r.month: r for r in result.months[strategy, rule]}
            level, path = 1.0, []
            totals: dict[str, float] = {}
            for month in result.common_months:
                level *= 1 + by_month[month].total_return
                path.append(level)
                for ticker, weight in by_month[month].weights:
                    totals[ticker] = totals.get(ticker, 0.0) + weight
            wealth[rule][strategy] = path
            average_weights[rule][strategy] = {
                ticker: total / len(result.common_months) for ticker, total in totals.items()
            }
            crisis[rule][strategy] = {}
            for name, (start, end) in CRISIS_WINDOWS.items():
                stat = window_stat(result.months[strategy, rule], start, end)
                crisis[rule][strategy][name] = (
                    None
                    if stat is None
                    else {
                        "cumulative": stat.cumulative_return,
                        "max_drawdown": stat.max_drawdown,
                        "min_coverage": stat.min_coverage,
                        "months": stat.months,
                    }
                )

    calendar = sorted(returns["SPY"])
    position = {month: i for i, month in enumerate(calendar)}
    tickers = [t for t in anchors if (t, t) in analysis.correlation]
    month_ends = [row.month_end for row in regime_rows]
    equity = bear_state(equity_levels, month_ends) if regime_rows else None
    macro = market_context(macro_points or {}, month_ends)
    return {
        "generated_on": generated_on.isoformat(),
        "as_of": analysis.as_of.isoformat(),
        "calc_version": BACKTEST_CALC_VERSION,
        "period": {
            "start": result.common_months[0].isoformat(),
            "end": result.common_months[-1].isoformat(),
            "months": len(result.common_months),
        },
        "rules": list(RULES),
        "strategies": strategy_ids,
        "months": [month.isoformat() for month in result.common_months],
        "performance": performance,
        "wealth": wealth,
        "average_weights": average_weights,
        "crisis": crisis,
        "crisis_windows": list(CRISIS_WINDOWS),
        "risk": [
            {
                "ticker": a.ticker,
                "months": a.months,
                "volatility": a.volatility,
                "max_drawdown": a.max_drawdown,
                "var_95": a.var_95,
                "risk_share": analysis.risk_contribution.get(a.ticker),
            }
            for a in analysis.assets
        ],
        "correlation": {
            "tickers": tickers,
            "window_months": analysis.window_months,
            "matrix": [[analysis.correlation[a, b] for b in tickers] for a in tickers],
        },
        "cash_ticker": cash_ticker,
        "assets": [
            {
                "ticker": a.ticker,
                "name": a.name,
                "level": a.level,
                "group": a.group,
                "role": a.role,
                "anchor": a.ticker in anchors,
            }
            for a in universe
        ],
        "calendar": [month.isoformat() for month in calendar],
        "returns": {
            ticker: _aligned(by_month, position, len(calendar))
            for ticker, by_month in returns.items()
        },
        "proxy": {
            ticker: [position[m] for m in months if m in position]
            for ticker, months in proxy_months.items()
            if months
        },
        "regime": _regime_payload(
            regime_rows,
            {t: returns[t] for t in tickers_in(universe, returns)},
            equity=equity,
            macro=macro,
            quadrants_ip=quadrants_ip,
        ),
        "regime_long": _long_payload(long_context, universe) if long_context else None,
        "proxies": list(proxies),
        "dividends": dict(dividends or {}),
        "charts": dict(charts or {}),
        "equity": equity,
        "macro": macro,
        "definitions": {
            s.id: {
                "kind": s.kind,
                "role": s.role,
                "weights": s.weights,
                "members": list(s.members),
                "max_weight": s.max_weight,
            }
            for s in strategies
        },
    }


def tickers_in(universe: Sequence[UniverseAsset], returns: Mapping[str, object]) -> list[str]:
    return [a.ticker for a in universe if a.ticker in returns]


def _regime_payload(
    rows: Sequence[RegimeRow],
    returns: Mapping[str, Mapping[date, float]],
    *,
    equity: dict | None,
    macro: dict | None,
    quadrants_ip: Sequence[str | None] | None = None,
) -> dict | None:
    if not rows:
        return None
    labels: dict[str, list[str | None]] = {
        "quadrant": [row.quadrant for row in rows],
        "indpro_sahm": [None if row.indpro_sahm is None else str(row.indpro_sahm) for row in rows],
        "correlation_regime": [row.correlation_regime for row in rows],
    }
    if quadrants_ip is not None:
        labels["quadrant_ip"] = list(quadrants_ip)
    if equity:
        labels["bear"] = [None if flag is None else str(flag) for flag in equity["bear"]]
    curve = macro["series"].get("T10Y3M") if macro else None
    if curve:
        labels["curve"] = [None if v is None else "inverted" if v < 0 else "normal" for v in curve]
    return {
        "calc_version": REGIME_PERFORMANCE_VERSION,
        "rows": [
            {
                "month": row.month_end.isoformat(),
                "quadrant": row.quadrant,
                "recession": row.indpro_sahm,
                "correlation_regime": row.correlation_regime,
                "quadrant_ip": None if quadrants_ip is None else quadrants_ip[i],
                "sahm": row.sahm,
                "cfnai_ma3": row.cfnai_ma3,
                "indpro_yoy": row.indpro_yoy,
                "stock_bond_correlation": row.stock_bond_correlation,
            }
            for i, row in enumerate(rows)
        ],
        "performance": regime_performance(labels, [row.month_end for row in rows], returns),
    }


def _long_payload(context: LongContext, universe: Sequence[UniverseAsset]) -> dict | None:
    rows = context.rows
    if not rows:
        return None
    month_ends = [row.month_end for row in rows]
    returns = {t: context.returns[t] for t in tickers_in(universe, context.returns)}
    equity = bear_state(context.equity_levels, month_ends)
    macro = market_context(context.macro_points, month_ends)
    payload = _regime_payload(
        rows, returns, equity=equity, macro=macro, quadrants_ip=context.quadrants_ip
    )
    calendar = sorted({month for by_month in returns.values() for month in by_month})
    position = {month: i for i, month in enumerate(calendar)}
    assert payload is not None
    payload |= {
        "equity": equity,
        "macro": macro,
        "calendar": [month.isoformat() for month in calendar],
        "returns": {
            ticker: _aligned(by_month, position, len(calendar))
            for ticker, by_month in returns.items()
        },
    }
    return payload


def _aligned(
    by_month: Mapping[date, float], position: Mapping[date, int], size: int
) -> list[float | None]:
    values: list[float | None] = [None] * size
    for month, value in by_month.items():
        if month in position:
            values[position[month]] = round(value, 8)
    return values


def render_dashboard(payload: dict) -> str:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    # "</" would end the script element early; JSON allows the escaped slash.
    data = json.dumps(payload, ensure_ascii=False, allow_nan=False).replace("</", "<\\/")
    engine = ENGINE_PATH.read_text(encoding="utf-8")
    return template.replace(_ENGINE_PLACEHOLDER, engine, 1).replace(_DATA_PLACEHOLDER, data, 1)

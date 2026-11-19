"""Static HTML report of the M1 results. Pure: takes computed results, returns one HTML string."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from html import escape
from math import log

from asset_frame.backtest.engine import CALC_VERSION as BACKTEST_CALC_VERSION
from asset_frame.backtest.jobs import CRISIS_WINDOWS, BacktestResult, Row, window_stat
from asset_frame.universe_jobs import Analysis

DISPLAY_RULE = "quarterly"
BENCHMARKS = (("bench_spy", "SPY 100%"), ("bench_6040", "60/40"))
SERIES_COLORS = ("--c1", "--c2", "--c3", "--c4", "--c5", "--c6", "--c7", "--c8")

_STYLE = """
:root { --bg:#f6f8fa; --surface:#fff; --fg:#16212b; --muted:#5b6a78; --line:#d9e0e6; --accent:#0b6e8a;
  --pos:#2f7d4f; --neg:#b3402a; --warn-bg:#fbeedb; --warn-fg:#7a4709;
  --c1:#16212b; --c2:#5b6a78; --c3:#0b6e8a; --c4:#b4690e; --c5:#2f7d4f; --c6:#8a3f9a; --c7:#c2410c; --c8:#1d4ed8; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg:#10171d; --surface:#17212a; --fg:#e4ebf1; --muted:#93a3b1; --line:#2a3945; --accent:#5cc2dd;
  --pos:#6fcf93; --neg:#f08a72; --warn-bg:#3a2a14; --warn-fg:#f0c98b;
  --c1:#e4ebf1; --c2:#93a3b1; --c3:#5cc2dd; --c4:#f0b160; --c5:#6fcf93; --c6:#d29be0; --c7:#f59e6b; --c8:#8fb0ff; color-scheme: dark; } }
:root[data-theme="dark"] {
  --bg:#10171d; --surface:#17212a; --fg:#e4ebf1; --muted:#93a3b1; --line:#2a3945; --accent:#5cc2dd;
  --pos:#6fcf93; --neg:#f08a72; --warn-bg:#3a2a14; --warn-fg:#f0c98b;
  --c1:#e4ebf1; --c2:#93a3b1; --c3:#5cc2dd; --c4:#f0b160; --c5:#6fcf93; --c6:#d29be0; --c7:#f59e6b; --c8:#8fb0ff; color-scheme: dark; }
body { background:var(--bg); color:var(--fg); margin:0; font:14px/1.6 system-ui,-apple-system,"Noto Sans KR",sans-serif;
  padding-block:28px 56px; padding-left:max(16px,env(safe-area-inset-left,0px)); padding-right:max(16px,env(safe-area-inset-right,0px)); }
main { max-width:1000px; margin:0 auto; display:flex; flex-direction:column; gap:28px; }
h1 { font-size:26px; margin:0; } h2 { font-size:15px; margin:0 0 8px; letter-spacing:.02em; }
p { margin:0; } .muted { color:var(--muted); font-size:13px; }
.warn { background:var(--warn-bg); color:var(--warn-fg); border-radius:6px; padding:12px 14px; }
.warn ul { margin:6px 0 0; padding-left:18px; }
.scroll { overflow-x:auto; } table { border-collapse:collapse; font-size:13px; font-variant-numeric:tabular-nums; }
th,td { padding:5px 9px; border-bottom:1px solid var(--line); text-align:right; white-space:nowrap; }
th { color:var(--muted); font-weight:500; } th:first-child,td:first-child,td.l,th.l { text-align:left; }
.pos { color:var(--pos); } .neg { color:var(--neg); }
svg { width:100%; height:auto; display:block; background:var(--surface); border:1px solid var(--line); border-radius:6px; }
svg text { fill:var(--muted); font-size:11px; } .legend { display:flex; flex-wrap:wrap; gap:4px 16px; margin-top:6px; font-size:13px; }
.legend i { display:inline-block; width:14px; height:3px; margin-right:6px; vertical-align:middle; }
section { min-width:0; }
"""


def render_report(
    result: BacktestResult,
    analysis: Analysis,
    *,
    strategy_ids: Sequence[str],
    anchors: Sequence[str],
    generated_on: date,
) -> str:
    first, last = result.common_months[0], result.common_months[-1]
    parts = [
        f"<h1>Asset_Frame 월간 리포트</h1><p class='muted'>생성 {generated_on} · 데이터 기준 {analysis.as_of}"
        f" · 비교 구간 {first} ~ {last}({len(result.common_months)}개월) · 계산 버전 {BACKTEST_CALC_VERSION}</p>",
        _limits(first),
        _performance_table(result, strategy_ids),
        _crisis_table(result, strategy_ids),
        _wealth_chart(result, strategy_ids),
        _risk_table(analysis),
        _correlation_table(analysis, anchors),
    ]
    body = "\n".join(
        f"<section>{part}</section>" if not part.startswith("<h1>") else part for part in parts
    )
    return (
        "<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Asset_Frame 월간 리포트</title><style>{_STYLE}</style></head><body><main>{body}</main></body></html>"
    )


def _limits(first: date) -> str:
    return (
        "<div class='warn'><b>읽기 전에</b><ul>"
        "<li>거래비용과 세금을 반영하지 않은 백테스트입니다(M3·M4에서 반영).</li>"
        f"<li>성과표는 모든 전략이 의도한 비중을 다 담는 {first} 이후만 비교합니다. 그 전 구간은 자산이 상장 전이라 구성이 다릅니다.</li>"
        "<li>월말 값 기준이라 달 안의 낙폭은 보이지 않습니다.</li>"
        "<li>표본이 짧습니다(침체 3번 안팎). 순위 차이가 우연일 수 있습니다.</li>"
        "<li>위험균등 전략은 변동성이 매우 낮은 현금에 비중이 크게 쏠립니다(개념 카드 참고).</li>"
        "</ul></div>"
    )


def _pct(value: float | None, digits: int = 1) -> str:
    return "-" if value is None else f"{value * 100:.{digits}f}%"


def _num(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def _signed(value: float | None) -> str:
    if value is None:
        return "-"
    css = "pos" if value > 0 else "neg" if value < 0 else ""
    return f"<span class='{css}'>{value * 100:+.1f}%</span>"


def _mark(better: bool) -> str:
    return "<span class='pos'>✓</span>" if better else "<span class='neg'>✗</span>"


def _performance_table(result: BacktestResult, ids: Sequence[str]) -> str:
    rows_by_key = {(row.strategy, row.rule): row for row in result.rows}
    head = (
        "<tr><th>전략</th><th>규칙</th><th>CAGR</th><th>변동성</th><th>샤프</th><th>소르티노</th>"
        "<th>칼마</th><th>최대낙폭</th><th>월 회전율</th>"
        + "".join(
            f"<th>vs {label}<br>초과 CAGR</th><th>정보비율</th><th>샤프↑ 낙폭↓</th>"
            for _, label in BENCHMARKS
        )
        + "</tr>"
    )
    lines = []
    for strategy_id in ids:
        for rule in ("monthly", "quarterly", "band"):
            row = rows_by_key.get((strategy_id, rule))
            if row is not None:
                lines.append(_performance_row(row, rows_by_key))
    return (
        "<h2>전략 성과표 (같은 구간·같은 구성)</h2>"
        "<p class='muted'>✓는 같은 규칙의 벤치마크보다 샤프가 높고 최대낙폭이 작다는 뜻입니다(PRD 2절).</p>"
        f"<div class='scroll'><table>{head}{''.join(lines)}</table></div>"
    )


def _performance_row(row: Row, rows_by_key: dict[tuple[str, str], Row]) -> str:
    p = row.performance
    cells = [
        f"<td class='l'>{escape(row.strategy)}</td><td class='l'>{escape(row.rule)}</td>",
        f"<td>{_pct(p.cagr)}</td><td>{_pct(p.volatility)}</td><td>{_num(p.sharpe)}</td>",
        f"<td>{_num(p.sortino)}</td><td>{_num(p.calmar)}</td><td>{_pct(p.max_drawdown)}</td>",
        f"<td>{_pct(row.mean_turnover, 2)}</td>",
    ]
    for name, _ in BENCHMARKS:
        relative, bench = row.versus.get(name), rows_by_key.get((name, row.rule))
        if relative is None or bench is None or row.strategy == name:
            cells.append("<td>-</td><td>-</td><td>-</td>")
            continue
        better_sharpe = (
            p.sharpe is not None
            and bench.performance.sharpe is not None
            and p.sharpe > bench.performance.sharpe
        )
        smaller_drawdown = p.max_drawdown > bench.performance.max_drawdown
        cells.append(
            f"<td>{_signed(relative.excess_cagr)}</td><td>{_num(relative.information_ratio)}</td>"
            f"<td>{_mark(better_sharpe)} {_mark(smaller_drawdown)}</td>"
        )
    return f"<tr>{''.join(cells)}</tr>"


def _crisis_table(result: BacktestResult, ids: Sequence[str]) -> str:
    head = (
        "<tr><th>전략</th>"
        + "".join(f"<th>{escape(name)}</th>" for name in CRISIS_WINDOWS)
        + "</tr>"
    )
    lines = []
    for strategy_id in ids:
        cells = []
        for start, end in CRISIS_WINDOWS.values():
            stat = window_stat(result.months[strategy_id, DISPLAY_RULE], start, end)
            if stat is None:
                cells.append("<td>-</td>")
                continue
            partial = "*" if stat.min_coverage < 1 - 1e-9 else ""
            cells.append(
                f"<td>{_signed(stat.cumulative_return)} / {_pct(stat.max_drawdown)}{partial}</td>"
            )
        lines.append(f"<tr><td class='l'>{escape(strategy_id)}</td>{''.join(cells)}</tr>")
    return (
        f"<h2>위기 구간 비교 ({DISPLAY_RULE} 리밸런싱)</h2>"
        "<p class='muted'>누적 수익률 / 구간 안 최대낙폭. * 는 일부 자산이 상장 전이거나 추정 창이 모자라 "
        "의도한 비중을 다 담지 못한 달이 있다는 표시, - 는 그 구간에 시작하지 못한 전략입니다.</p>"
        f"<div class='scroll'><table>{head}{''.join(lines)}</table></div>"
    )


def _wealth_chart(result: BacktestResult, ids: Sequence[str]) -> str:
    width, height, left, bottom, top = 760, 340, 48, 24, 10
    series = {}
    for strategy_id in ids:
        by_month = {r.month: r.total_return for r in result.months[strategy_id, DISPLAY_RULE]}
        wealth, points = 1.0, [1.0]
        for month in result.common_months:
            wealth *= 1 + by_month[month]
            points.append(wealth)
        series[strategy_id] = points
    low = min(min(points) for points in series.values())
    high = max(max(points) for points in series.values())
    span = max(log(high) - log(low), 1e-9)
    count = len(result.common_months)

    def x(i: int) -> float:
        return left + (width - left - 10) * i / count

    def y(value: float) -> float:
        return top + (height - top - bottom) * (1 - (log(value) - log(low)) / span)

    ticks = sorted({round(low, 2), 1.0, round(high, 2)})
    grid = "".join(
        f"<line x1='{left}' x2='{width - 10}' y1='{y(t):.1f}' y2='{y(t):.1f}' stroke='var(--line)'/>"
        f"<text x='{left - 6}' y='{y(t) + 4:.1f}' text-anchor='end'>{t:.2f}</text>"
        for t in ticks
    )
    lines = "".join(
        f"<polyline fill='none' stroke='var({SERIES_COLORS[i % len(SERIES_COLORS)]})' stroke-width='1.6'"
        f"{' stroke-dasharray="5 3"' if strategy_id.startswith('bench') else ''} points='"
        + " ".join(f"{x(j):.1f},{y(v):.1f}" for j, v in enumerate(points))
        + "'/>"
        for i, (strategy_id, points) in enumerate(series.items())
    )
    axis = (
        f"<text x='{left}' y='{height - 6}'>{result.common_months[0]}</text>"
        f"<text x='{width - 10}' y='{height - 6}' text-anchor='end'>{result.common_months[-1]}</text>"
    )
    legend = "".join(
        f"<span><i style='background:var({SERIES_COLORS[i % len(SERIES_COLORS)]})'></i>{escape(sid)}</span>"
        for i, sid in enumerate(series)
    )
    return (
        f"<h2>누적 가치 (시작=1, 로그 축, {DISPLAY_RULE})</h2>"
        f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='전략별 누적 가치'>{grid}{lines}{axis}</svg>"
        f"<div class='legend'>{legend}</div>"
    )


def _risk_table(analysis: Analysis) -> str:
    head = (
        "<tr><th>자산</th><th>월 수</th><th>변동성</th><th>최대낙폭</th><th>95% VaR(1개월)</th>"
        "<th>동일가중 위험 몫</th></tr>"
    )
    lines = "".join(
        f"<tr><td class='l'>{escape(a.ticker)}</td><td>{a.months}</td><td>{_pct(a.volatility)}</td>"
        f"<td>{_pct(a.max_drawdown)}</td><td>{_pct(a.var_95)}</td>"
        f"<td>{_pct(analysis.risk_contribution.get(a.ticker))}</td></tr>"
        for a in analysis.assets
    )
    return (
        "<h2>자산별 위험</h2><p class='muted'>변동성·낙폭·VaR은 각 자산의 전체 이력 기준입니다. "
        "위험 몫은 자산군 앵커 12개를 동일가중했을 때 최근 36개월 분산 중 차지하는 비율입니다.</p>"
        f"<div class='scroll'><table>{head}{lines}</table></div>"
    )


def _correlation_table(analysis: Analysis, anchors: Sequence[str]) -> str:
    tickers = [t for t in anchors if (t, t) in analysis.correlation]
    head = "<tr><th></th>" + "".join(f"<th>{escape(t)}</th>" for t in tickers) + "</tr>"
    lines = []
    for first in tickers:
        cells = []
        for second in tickers:
            value = analysis.correlation[first, second]
            if value is None:
                cells.append("<td>-</td>")
                continue
            tone = "var(--pos)" if value >= 0 else "var(--neg)"
            cells.append(
                f"<td style='background:color-mix(in srgb,{tone} {abs(value) * 45:.0f}%,transparent)'>{value:.2f}</td>"
            )
        lines.append(f"<tr><td class='l'>{escape(first)}</td>{''.join(cells)}</tr>")
    return (
        f"<h2>상관행렬 (자산군 앵커, 최근 {analysis.window_months}개월, {analysis.as_of} 기준)</h2>"
        "<p class='muted'>상관은 국면에 따라 변합니다. 이 표는 현재 창의 한 시점입니다.</p>"
        f"<div class='scroll'><table>{head}{''.join(lines)}</table></div>"
    )

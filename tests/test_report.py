from datetime import date
from html.parser import HTMLParser
from pathlib import Path

import pytest

from asset_frame.backtest.engine import MonthResult
from asset_frame.backtest.jobs import run_backtest, window_stat
from asset_frame.backtest.strategies import Strategy, load_strategies
from asset_frame.report.html import render_report
from asset_frame.universe import load_universe
from asset_frame.universe_jobs import Analysis, AssetRisk

UNIVERSE = load_universe(Path("config/universe.toml"))
STRATEGIES = tuple(
    s
    for s in load_strategies(Path("config/strategies.toml"), UNIVERSE)
    if s.id in ("bench_spy", "bench_6040")
)


def months(count: int) -> list[date]:
    return [date(2000 + n // 12, n % 12 + 1, 28) for n in range(count)]


def test_window_stat_hand_calculation_and_partial_coverage() -> None:
    results = (
        MonthResult(date(2008, 1, 31), 0.10, 1.0, 0.0),
        MonthResult(date(2008, 2, 29), -0.20, 0.5, 0.0),
        MonthResult(date(2009, 1, 31), 0.05, 1.0, 0.0),
    )
    stat = window_stat(results, date(2008, 1, 1), date(2008, 12, 31))
    assert stat is not None
    assert stat.months == 2
    assert stat.cumulative_return == pytest.approx(1.1 * 0.8 - 1)
    assert stat.max_drawdown == pytest.approx(-0.20)
    assert stat.min_coverage == 0.5
    assert window_stat(results, date(2015, 1, 1), date(2015, 12, 31)) is None


class TagChecker(HTMLParser):
    """Counts open/close tags of non-void elements to catch unbalanced markup."""

    VOID = {"meta", "line", "br", "polyline"}

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []

    def handle_starttag(self, tag, attrs):  # type: ignore[no-untyped-def]
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):  # type: ignore[no-untyped-def]
        if tag not in self.VOID:
            assert self.stack.pop() == tag


def test_report_contains_every_section_and_balanced_markup() -> None:
    calendar = months(40)
    returns = {
        "SPY": {m: 0.01 + 0.002 * (n % 3) for n, m in enumerate(calendar)},
        "IEF": {m: 0.004 - 0.001 * (n % 2) for n, m in enumerate(calendar)},
        "BIL": {m: 0.002 for m in calendar},
    }
    result = run_backtest(STRATEGIES, returns, cash_ticker="BIL")
    analysis = Analysis(
        as_of=calendar[-1],
        window_months=36,
        assets=(AssetRisk("SPY", 40, 0.1, -0.2, 0.05),),
        correlation={
            ("SPY", "SPY"): 1.0,
            ("SPY", "IEF"): -0.3,
            ("IEF", "SPY"): -0.3,
            ("IEF", "IEF"): 1.0,
        },
        risk_contribution={"SPY": 0.6, "IEF": 0.4},
        excluded=(),
    )

    html = render_report(
        result,
        analysis,
        strategy_ids=["bench_spy", "bench_6040"],
        anchors=["SPY", "IEF"],
        generated_on=date(2026, 11, 19),
    )

    for text in (
        "전략 성과표",
        "위기 구간 비교",
        "누적 가치",
        "자산별 위험",
        "상관행렬",
        "bench_6040",
        "-0.30",
    ):
        assert text in html
    checker = TagChecker()
    checker.feed(html)
    assert checker.stack == []


def test_report_escapes_strategy_names() -> None:
    calendar = months(40)
    returns = {
        "SPY": {m: 0.01 + 0.002 * (n % 3) for n, m in enumerate(calendar)},
        "IEF": {m: 0.004 for m in calendar},
        "BIL": {m: 0.002 for m in calendar},
    }
    odd = Strategy("<b>odd</b>", "r", "fixed", weights={"SPY": 1.0})
    benchmarks = tuple(s for s in STRATEGIES)
    result = run_backtest((*benchmarks, odd), returns, cash_ticker="BIL")
    analysis = Analysis(calendar[-1], 36, (), {}, {}, ())

    html = render_report(
        result,
        analysis,
        strategy_ids=["bench_spy", "bench_6040", "<b>odd</b>"],
        anchors=[],
        generated_on=date(2026, 11, 19),
    )

    assert "&lt;b&gt;odd&lt;/b&gt;" in html
    assert "<b>odd</b>" not in html

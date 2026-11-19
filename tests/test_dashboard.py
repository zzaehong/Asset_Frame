import json
import re
from datetime import date
from pathlib import Path

import pytest

from asset_frame.backtest.jobs import run_backtest
from asset_frame.backtest.strategies import load_strategies
from asset_frame.report.dashboard import build_payload, render_dashboard
from asset_frame.universe import load_universe
from asset_frame.universe_jobs import Analysis, AssetRisk

UNIVERSE = load_universe(Path("config/universe.toml"))
STRATEGIES = tuple(
    s
    for s in load_strategies(Path("config/strategies.toml"), UNIVERSE)
    if s.id in ("bench_spy", "bench_6040", "permanent")
)


def months(count: int) -> list[date]:
    return [date(2000 + n // 12, n % 12 + 1, 28) for n in range(count)]


@pytest.fixture
def payload() -> dict:
    calendar = months(60)
    returns = {
        "SPY": {m: 0.01 + 0.002 * (n % 3) for n, m in enumerate(calendar)},
        "IEF": {m: 0.004 - 0.001 * (n % 2) for n, m in enumerate(calendar)},
        "TLT": {m: 0.005 + 0.003 * (n % 4) for n, m in enumerate(calendar)},
        "GLD": {m: 0.006 - 0.002 * (n % 3) for n, m in enumerate(calendar)},
        "BIL": {m: 0.002 for m in calendar},
    }
    result = run_backtest(STRATEGIES, returns, cash_ticker="BIL")
    analysis = Analysis(
        as_of=calendar[-1],
        window_months=36,
        assets=(AssetRisk("SPY", 60, 0.1, -0.2, 0.05), AssetRisk("IEF", 60, 0.05, -0.1, 0.02)),
        correlation={
            ("SPY", "SPY"): 1.0,
            ("SPY", "IEF"): -0.3,
            ("IEF", "SPY"): -0.3,
            ("IEF", "IEF"): 1.0,
        },
        risk_contribution={"SPY": 0.6, "IEF": 0.4},
        excluded=(),
    )
    return build_payload(
        result,
        analysis,
        strategy_ids=[s.id for s in STRATEGIES],
        anchors=["SPY", "IEF"],
        generated_on=date(2026, 11, 19),
    )


def test_wealth_is_the_running_product_of_the_monthly_returns(payload: dict) -> None:
    path = payload["wealth"]["quarterly"]["bench_spy"]
    assert len(path) == payload["period"]["months"] == len(payload["months"])
    # first compared month: calendar index 13 (13 months of history), SPY 0.01 + 0.002 * (13 % 3)
    assert path[0] == pytest.approx(1.012)
    assert path[1] / path[0] > 1.0
    # every strategy is on the same months, and each rule is present
    assert set(payload["wealth"]) == set(payload["rules"]) == {"monthly", "quarterly", "band"}
    assert {len(v) for v in payload["wealth"]["band"].values()} == {len(payload["months"])}


def test_benchmark_flags_compare_sharpe_and_drawdown_with_the_same_rule(payload: dict) -> None:
    perf = payload["performance"]["monthly"]
    assert "bench_spy" not in perf["bench_spy"]["versus"]  # a benchmark has no edge over itself
    flags = perf["permanent"]["versus"]["bench_6040"]
    expected_sharpe = perf["permanent"]["sharpe"] > perf["bench_6040"]["sharpe"]
    expected_drawdown = perf["permanent"]["max_drawdown"] > perf["bench_6040"]["max_drawdown"]
    assert flags["better_sharpe"] is expected_sharpe
    assert flags["smaller_drawdown"] is expected_drawdown


def test_crisis_windows_without_months_are_none(payload: dict) -> None:
    # the synthetic calendar runs 2000-2004, so no crisis window has a month
    assert set(payload["crisis"]["monthly"]["bench_spy"].values()) == {None}
    assert payload["crisis_windows"] == ["2008 금융위기", "2020 코로나", "2022 금리 인상"]


def test_dashboard_is_one_offline_file_with_parseable_embedded_data(payload: dict) -> None:
    html = render_dashboard(payload)

    data = re.search(r"const D = (.*?);\nconst RULE_LABEL", html, re.S)
    assert data is not None
    assert json.loads(data.group(1))["period"] == payload["period"]
    # nothing is loaded from outside the file
    assert not re.search(
        r"<link\b|\bsrc=|@import|url\(|fetch\(|XMLHttpRequest|https?://(?!www\.w3\.org/2000/svg)",
        html,
    )
    assert html.count("<script>") == 1


def test_embedded_data_cannot_close_the_script_element(payload: dict) -> None:
    payload["strategies"][0] = "</script><b>x"
    html = render_dashboard(payload)
    assert html.count("</script>") == 1

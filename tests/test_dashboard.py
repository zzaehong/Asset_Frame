import json
import re
from datetime import date
from pathlib import Path

import pytest

from asset_frame.backtest.engine import MonthResult
from asset_frame.backtest.jobs import run_backtest, window_stat
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


def make_inputs() -> tuple:
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
    return result, analysis, returns, calendar


@pytest.fixture
def payload() -> dict:
    result, analysis, returns, calendar = make_inputs()
    return build_payload(
        result,
        analysis,
        universe=UNIVERSE,
        strategies=STRATEGIES,
        returns=returns,
        proxy_months={"BIL": calendar[:3]},
        cash_ticker="BIL",
        generated_on=date(2026, 11, 19),
    )


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


def test_cash_is_an_ordinary_asset_in_the_payload(payload: dict) -> None:
    cash = next(a for a in payload["assets"] if a["ticker"] == "BIL")
    assert cash["group"] == "cash"
    assert len(payload["returns"]["BIL"]) == len(payload["calendar"])
    assert payload["proxy"]["BIL"] == [0, 1, 2]
    # permanent holds 25% cash on average, and the benchmarks hold none
    average = payload["average_weights"]["quarterly"]
    assert average["permanent"]["BIL"] == pytest.approx(0.25, abs=0.05)
    assert "BIL" not in average["bench_spy"]
    assert payload["definitions"]["permanent"]["weights"]["BIL"] == 0.25


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

    data = re.search(r"const D = (.*?);\n// Backtest and risk functions", html, re.S)
    assert data is not None
    assert json.loads(data.group(1))["period"] == payload["period"]
    # nothing is loaded from outside the file
    assert not re.search(
        r"<link\b|\bsrc=|@import|url\(|fetch\(|XMLHttpRequest|https?://(?!www\.w3\.org/2000/svg)",
        html,
    )
    assert html.count("<script>") == html.count("</script>") == 2  # data + engine, then the page


def test_embedded_data_cannot_close_the_script_element(payload: dict) -> None:
    payload["strategies"][0] = "</script><b>x"
    html = render_dashboard(payload)
    assert html.count("</script>") == 2  # only the two real closing tags


def test_payload_regime_section_is_absent_without_rows_and_carries_performance_with_them() -> None:
    from asset_frame.regime.replay import RegimeRow

    result, analysis, returns, calendar = make_inputs()
    kwargs = dict(
        universe=UNIVERSE,
        strategies=STRATEGIES,
        returns=returns,
        proxy_months={},
        cash_ticker="BIL",
        generated_on=date(2026, 1, 1),
    )
    assert build_payload(result, analysis, **kwargs)["regime"] is None

    rows = [
        RegimeRow(
            month_end=calendar[i],
            sahm=None,
            indpro_yoy=None,
            cfnai_ma3=None,
            indpro_sahm=False,
            cfnai_sahm=None,
            quadrant="growth_up_inflation_up",
            stock_bond_correlation=None,
            correlation_regime=None,
            nber_recession=False,
        )
        for i in range(10)
    ]
    regime = build_payload(result, analysis, regime_rows=rows, **kwargs)["regime"]

    performance = regime["performance"]
    cell = performance["axes"]["quadrant"]["growth_up_inflation_up"]
    assert cell["months"] == 10 and "SPY" in cell["assets"]
    assert performance["horizons"] == [1, 3, 6, 12, 24, 36] and performance["all"]["months"] == 10
    json.dumps(regime, allow_nan=False)


def test_payload_macro_section_follows_the_regime_months() -> None:
    from asset_frame.regime.replay import RegimeRow

    result, analysis, returns, calendar = make_inputs()
    rows = [
        RegimeRow(
            month_end=calendar[i],
            sahm=None,
            indpro_yoy=None,
            cfnai_ma3=None,
            indpro_sahm=False,
            cfnai_sahm=None,
            quadrant=None,
            stock_bond_correlation=None,
            correlation_regime=None,
            nber_recession=False,
        )
        for i in range(3)
    ]
    kwargs = dict(
        universe=UNIVERSE,
        strategies=STRATEGIES,
        returns=returns,
        proxy_months={},
        cash_ticker="BIL",
        generated_on=date(2026, 1, 1),
        regime_rows=rows,
    )
    macro = build_payload(
        result, analysis, macro_points={"T10Y3M": [(calendar[0], 0.5)]}, **kwargs
    )["macro"]

    assert macro["months"] == [row.month_end.isoformat() for row in rows]
    assert macro["series"]["T10Y3M"][0] == 0.5
    assert build_payload(result, analysis, **kwargs)["macro"] is None


def test_payload_equity_section_flags_a_bear_market_from_levels() -> None:
    from asset_frame.regime.replay import RegimeRow

    result, analysis, returns, calendar = make_inputs()
    rows = [
        RegimeRow(
            month_end=calendar[i],
            sahm=None,
            indpro_yoy=None,
            cfnai_ma3=None,
            indpro_sahm=False,
            cfnai_sahm=None,
            quadrant=None,
            stock_bond_correlation=None,
            correlation_regime=None,
            nber_recession=False,
        )
        for i in range(2)
    ]
    levels = [
        (date(2000, 1, 3), 100.0),
        (calendar[0], 100.0),
        (date(2000, 2, 10), 70.0),
        (calendar[1], 75.0),
    ]
    kwargs = dict(
        universe=UNIVERSE,
        strategies=STRATEGIES,
        returns=returns,
        proxy_months={},
        cash_ticker="BIL",
        generated_on=date(2026, 1, 1),
        regime_rows=rows,
    )

    equity = build_payload(result, analysis, equity_levels=levels, **kwargs)["equity"]

    assert equity["bear"] == [False, True]
    assert build_payload(result, analysis, **kwargs)["equity"] is None


def test_payload_carries_dividends_only_when_given() -> None:
    result, analysis, returns, calendar = make_inputs()
    common = dict(
        universe=UNIVERSE,
        strategies=STRATEGIES,
        returns=returns,
        proxy_months={},
        cash_ticker="BIL",
        generated_on=date(2026, 11, 19),
    )
    assert build_payload(result, analysis, **common)["dividends"] == {}
    given = {"SPY": {"yield": 0.01, "annual": 7.5, "payments": 4}}
    assert build_payload(result, analysis, dividends=given, **common)["dividends"] == given

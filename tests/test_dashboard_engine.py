"""The dashboard's JavaScript engine must agree with the Python engine on the same data."""

import json
import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest

from asset_frame.analytics.risk import (
    aligned_window,
    correlation_matrix,
    covariance_matrix,
    risk_contributions,
)
from asset_frame.backtest.engine import RULES, run_strategy
from asset_frame.backtest.metrics import performance, relative
from asset_frame.backtest.strategies import Strategy

NODE = shutil.which("node")
RUNNER = Path(__file__).with_name("dashboard_engine_runner.js")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

SIZE = 90
CALENDAR = [date(2000 + n // 12, n % 12 + 1, 28) for n in range(SIZE)]
FIRST = {"SPY": 0, "IEF": 0, "TLT": 3, "GLD": 20, "BIL": 0}  # first calendar index with a return


def series(ticker: str) -> list[float | None]:
    start = FIRST[ticker]
    wiggle = {"SPY": 0.03, "IEF": 0.01, "TLT": 0.025, "GLD": 0.02, "BIL": 0.0}[ticker]
    base = {"SPY": 0.008, "IEF": 0.003, "TLT": 0.004, "GLD": 0.005, "BIL": 0.002}[ticker]
    return [
        None if n < start else base + wiggle * (((n * 7 + len(ticker)) % 11) - 5) / 5
        for n in range(SIZE)
    ]


RETURNS = {t: series(t) for t in FIRST}
FIXED = {
    "bench_6040": {"SPY": 0.6, "IEF": 0.4},
    "permanent": {"SPY": 25, "TLT": 25, "GLD": 25, "BIL": 25},  # unnormalised on purpose
    "late_start": {"SPY": 0.5, "GLD": 0.5},
}


@pytest.fixture(scope="module")
def js() -> dict:
    picked = RETURNS["SPY"][20:]
    payload = {
        "calendar": [d.isoformat() for d in CALENDAR],
        "returns": RETURNS,
        "rules": list(RULES),
        "targets": FIXED,
        "series": {
            "mine": [v for v in picked if v is not None],
            "bench": [v for v in RETURNS["IEF"][20:] if v is not None],
            "cash": [v for v in RETURNS["BIL"][20:] if v is not None],
        },
        "risk": {
            "tickers": ["SPY", "IEF", "TLT", "GLD"],
            "end": SIZE - 1,
            "window": 36,
            "weights": {"SPY": 0.4, "IEF": 0.3, "TLT": 0.2, "GLD": 0.1},
        },
        "roll": {"a": "SPY", "b": "TLT", "window": 24},
    }
    done = subprocess.run(
        [NODE, str(RUNNER)], input=json.dumps(payload), capture_output=True, text=True, check=True
    )
    return json.loads(done.stdout)


@pytest.mark.parametrize("name", list(FIXED))
@pytest.mark.parametrize("rule", RULES)
def test_backtest_matches_python(js: dict, name: str, rule: str) -> None:
    total = sum(FIXED[name].values())
    strategy = Strategy(name, "r", "fixed", weights={t: w / total for t, w in FIXED[name].items()})
    returns = {
        t: {m: v for m, v in zip(CALENDAR, values, strict=True) if v is not None}
        for t, values in RETURNS.items()
    }
    expected = run_strategy(strategy, returns, CALENDAR, rule)
    got = js["runs"][f"{name}|{rule}"]

    assert [CALENDAR[r["i"]] for r in got] == [r.month for r in expected]
    for mine, theirs in zip(got, expected, strict=True):
        assert mine["ret"] == pytest.approx(theirs.total_return, abs=1e-12)
        assert mine["coverage"] == pytest.approx(theirs.coverage, abs=1e-12)
        assert mine["turnover"] == pytest.approx(theirs.turnover, abs=1e-12)


def test_late_asset_lowers_coverage_then_restores_it(js: dict) -> None:
    runs = js["runs"]["late_start|monthly"]
    assert runs[0]["coverage"] == pytest.approx(0.5)
    assert runs[-1]["coverage"] == pytest.approx(1.0)


def test_performance_and_relative_match_python(js: dict) -> None:
    mine = [v for v in RETURNS["SPY"][20:] if v is not None]
    bench = [v for v in RETURNS["IEF"][20:] if v is not None]
    cash = [v for v in RETURNS["BIL"][20:] if v is not None]
    py, rel = performance(mine, cash), relative(mine, bench)
    for key in ("cagr", "volatility", "sharpe", "sortino", "calmar", "max_drawdown"):
        assert js["performance"][key] == pytest.approx(getattr(py, key), rel=1e-9)
    for key in ("excess_cagr", "tracking_error", "information_ratio"):
        assert js["relative"][key] == pytest.approx(getattr(rel, key), rel=1e-9)


def test_correlation_risk_and_rolling_match_python(js: dict) -> None:
    tickers = ["SPY", "IEF", "TLT", "GLD"]
    months = CALENDAR[-36:]
    by_month = {
        t: {m: v for m, v in zip(CALENDAR, RETURNS[t], strict=True) if v is not None}
        for t in tickers
    }
    window = aligned_window(by_month, months)
    expected = correlation_matrix(window)
    names = js["correlation"]["names"]
    assert names == [t for t in tickers if t in window]
    for i, a in enumerate(names):
        for j, b in enumerate(names):
            assert js["correlation"]["matrix"][i][j] == pytest.approx(expected[a, b], abs=1e-9)

    weights = {"SPY": 0.4, "IEF": 0.3, "TLT": 0.2, "GLD": 0.1}
    shares = risk_contributions(weights, covariance_matrix(window))
    for ticker, share in shares.items():
        assert js["risk"]["shares"][ticker] == pytest.approx(share, abs=1e-9)

    spy, tlt = RETURNS["SPY"], RETURNS["TLT"]
    last = js["rolling"][-1]
    xs, ys = spy[-24:], tlt[-24:]
    from statistics import correlation

    assert last == pytest.approx(correlation(xs, ys), abs=1e-9)  # type: ignore[arg-type]
    assert js["rolling"][22] is None  # fewer than 24 months


def test_stocks_toml_round_trips_through_the_python_loader(tmp_path: Path) -> None:
    from asset_frame.stocks import load_stocks
    from asset_frame.universe import load_universe

    selection = ["NVDA", "BRK-B", "JPM"]
    script = (
        "const E = require(process.argv[1]); "
        "console.log(JSON.stringify(E.stocksToml(JSON.parse(process.argv[2]))))"
    )
    engine = Path("src/asset_frame/report/dashboard_engine.js").resolve()
    out = subprocess.run(
        [NODE, "-e", script, str(engine), json.dumps(selection)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    path = tmp_path / "stocks.toml"
    path.write_text(json.loads(out))
    specs = load_stocks(path, load_universe(Path("config/universe.toml")))
    assert [s.ticker for s in specs] == selection


def test_stocks_toml_rejects_a_malformed_ticker() -> None:
    script = "const E = require(process.argv[1]); E.stocksToml(['bad ticker'])"
    engine = Path("src/asset_frame/report/dashboard_engine.js").resolve()
    result = subprocess.run([NODE, "-e", script, str(engine)], capture_output=True, text=True)
    assert result.returncode != 0 and "invalid ticker" in result.stderr

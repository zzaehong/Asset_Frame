from datetime import date
from pathlib import Path

import pytest

from asset_frame.backtest.engine import MINIMUM_HISTORY_MONTHS, run_strategy
from asset_frame.backtest.jobs import run_backtest
from asset_frame.backtest.metrics import performance, relative
from asset_frame.backtest.strategies import (
    Strategy,
    StrategyConfigError,
    load_strategies,
    target_weights,
)
from asset_frame.universe import load_universe

UNIVERSE = load_universe(Path("config/universe.toml"))
STRATEGIES = load_strategies(Path("config/strategies.toml"), UNIVERSE)
FIFTY_FIFTY = Strategy("s", "r", "fixed", weights={"A": 0.5, "B": 0.5})


def month_list(count: int) -> list[date]:
    return [date(2000 + n // 12, n % 12 + 1, 28) for n in range(count)]


def two_asset_returns(count: int = 30):
    months = month_list(count)
    # A grows faster, so the weights drift away from 50/50
    return months, {"A": {m: 0.10 for m in months}, "B": {m: 0.00 for m in months}}


def test_project_strategies_match_prd_7() -> None:
    by_id = {s.id: s for s in STRATEGIES}
    assert list(by_id) == [
        "bench_spy",
        "bench_6040",
        "all_weather_approx",
        "permanent",
        "equal_weight",
        "inv_vol",
        "erc",
        "min_variance",
        "min_variance_cap20",
        "min_variance_cap40",
    ]
    assert by_id["min_variance"].max_weight == 0.30
    assert by_id["min_variance_cap20"].max_weight == 0.20
    assert by_id["min_variance_cap40"].max_weight == 0.40
    assert by_id["bench_6040"].weights == {"SPY": 0.6, "IEF": 0.4}
    assert by_id["all_weather_approx"].weights["TLT"] == 0.40
    assert len(by_id["equal_weight"].members) == 12  # level-1 anchors


def test_weights_must_sum_to_one_and_use_universe_tickers(tmp_path: Path) -> None:
    bad_sum = tmp_path / "a.toml"
    bad_sum.write_text('[[strategies]]\nid="x"\nrole="r"\nkind="fixed"\nweights={SPY=0.5}\n')
    with pytest.raises(StrategyConfigError, match="sum to 1"):
        load_strategies(bad_sum, UNIVERSE)
    unknown = tmp_path / "b.toml"
    unknown.write_text('[[strategies]]\nid="x"\nrole="r"\nkind="fixed"\nweights={ZZZ=1.0}\n')
    with pytest.raises(StrategyConfigError, match="not in universe"):
        load_strategies(unknown, UNIVERSE)


def test_missing_assets_pass_their_weight_to_the_rest_and_lower_coverage() -> None:
    strategy = Strategy("s", "r", "fixed", weights={"A": 0.6, "B": 0.4})
    weights, coverage = target_weights(strategy, ["A"])
    assert weights == {"A": 1.0}
    assert coverage == pytest.approx(0.6)
    assert target_weights(strategy, []) == ({}, 0.0)


def test_history_rule_delays_the_first_month_by_thirteen_returns() -> None:
    months, returns = two_asset_returns()
    results = run_strategy(FIFTY_FIFTY, returns, months, "monthly")
    assert results[0].month == months[MINIMUM_HISTORY_MONTHS]


def test_monthly_rule_matches_a_hand_calculation() -> None:
    months, returns = two_asset_returns()
    results = run_strategy(FIFTY_FIFTY, returns, months, "monthly")
    assert all(r.total_return == pytest.approx(0.05) for r in results)
    # after a month A is 0.55 / 1.05 of the portfolio; half of its distance to 0.5 is traded
    assert results[1].turnover == pytest.approx(0.55 / 1.05 - 0.5)


def test_band_rule_waits_until_drift_exceeds_five_points() -> None:
    months, returns = two_asset_returns()
    results = run_strategy(FIFTY_FIFTY, returns, months, "band")
    # A's weight: 0.5238, 0.5455 (+4.5 points, inside), 0.5668 (+6.7, outside) -> 3rd drift
    rebalanced = [i for i, r in enumerate(results) if r.turnover > 0]
    assert rebalanced[0] == 3


def test_quarterly_rule_rebalances_only_at_quarter_starts() -> None:
    months, returns = two_asset_returns()
    results = run_strategy(FIFTY_FIFTY, returns, months, "quarterly")
    assert {r.month.month for r in results if r.turnover > 0} <= {1, 4, 7, 10}


def test_new_eligible_asset_forces_a_rebalance_and_restores_coverage() -> None:
    months = month_list(30)
    returns = {
        "A": {m: 0.01 for m in months},
        "B": {m: 0.01 for m in months[8:]},  # first return at index 8, eligible at index 21
    }
    results = run_strategy(FIFTY_FIFTY, returns, months, "band")
    assert results[0].coverage == pytest.approx(0.5)
    assert results[-1].coverage == pytest.approx(1.0)
    assert any(r.turnover > 0 for r in results)


def test_performance_hand_calculation() -> None:
    result = performance([0.10, -0.10], [0.0, 0.0])
    assert result.cagr == pytest.approx((1.1 * 0.9) ** 6 - 1)
    assert result.max_drawdown == pytest.approx(-0.10)
    assert result.sharpe == pytest.approx(0.0)
    assert result.calmar == pytest.approx(result.cagr / 0.10)


def test_sharpe_and_sortino_use_excess_over_cash() -> None:
    result = performance([0.02, 0.04], [0.01, 0.01])
    # excess 0.01, 0.03: mean 0.02, sample std 0.0141421; no negative excess -> no sortino
    assert result.sharpe == pytest.approx(0.02 * 12**0.5 / 0.0141421356, rel=1e-6)
    assert result.sortino is None
    # excess -0.01, 0.03: downside deviation sqrt(0.0001 / 2)
    mixed = performance([0.00, 0.04], [0.01, 0.01])
    assert mixed.sortino == pytest.approx(0.01 * 12**0.5 / (0.0001 / 2) ** 0.5)


def test_relative_metrics_hand_calculation() -> None:
    result = relative([0.03, 0.01], [0.01, 0.01])
    # active 0.02, 0.00: mean 0.01, sample std 0.0141421
    assert result.information_ratio == pytest.approx(0.01 * 12**0.5 / 0.0141421356, rel=1e-6)
    assert result.tracking_error == pytest.approx(0.0141421356 * 12**0.5)
    assert result.excess_cagr == pytest.approx((1.03 * 1.01) ** 6 - (1.01 * 1.01) ** 6)


def test_rows_share_one_period_and_a_benchmark_tracks_itself_exactly() -> None:
    months = month_list(40)
    returns = {
        "SPY": {m: 0.01 + 0.002 * (n % 3) for n, m in enumerate(months)},
        "IEF": {m: 0.004 - 0.001 * (n % 2) for n, m in enumerate(months)},
        "BIL": {m: 0.002 for m in months},
    }
    strategies = tuple(s for s in STRATEGIES if s.id in ("bench_spy", "bench_6040"))

    result = run_backtest(strategies, returns, cash_ticker="BIL")

    assert len(result.rows) == 6  # 2 strategies x 3 rules
    period = (result.common_months[0], result.common_months[-1])
    assert {(row.start, row.end) for row in result.rows} == {period}
    spy_row = next(r for r in result.rows if r.strategy == "bench_spy")
    assert spy_row.versus["bench_spy"].tracking_error == pytest.approx(0.0, abs=1e-12)


def test_estimated_strategy_uses_the_trailing_window_before_the_month() -> None:
    months = month_list(40)
    returns = {
        "A": {m: 0.01 if n % 2 == 0 else -0.01 for n, m in enumerate(months)},
        "B": {m: 0.02 if n % 2 == 0 else -0.02 for n, m in enumerate(months)},
    }
    strategy = Strategy("iv", "r", "inv_vol", members=("A", "B"))

    results = run_strategy(strategy, returns, months, "monthly", window_months=24)

    assert results[0].month == months[24]  # a full 24-month window must precede the month
    # volatilities 1 : 2 give weights 2/3, 1/3; month 24 is an up month for both
    assert results[0].total_return == pytest.approx(2 / 3 * 0.01 + 1 / 3 * 0.02)
    assert results[0].coverage == pytest.approx(1.0)


def test_estimated_strategy_needs_two_assets_with_a_full_window() -> None:
    months = month_list(40)
    returns = {"A": {m: 0.01 * (n % 3 - 1) for n, m in enumerate(months)}}
    strategy = Strategy("iv", "r", "inv_vol", members=("A", "B"))
    assert run_strategy(strategy, returns, months, "monthly", window_months=24) == ()

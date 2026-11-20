from datetime import date

import pytest

from asset_frame.regime.performance import regime_performance

M = [date(2020, m, 28) for m in range(1, 7)]  # Jan..Jun
RETURNS = {
    "A": dict(zip(M, [0.9, 0.10, -0.02, 0.04, 0.05, 0.01], strict=True)),
    "B": {M[0]: 0.9, M[1]: 0.01, M[3]: 0.02, M[4]: 0.0, M[5]: 0.0},  # March missing
}
LABELS = {"axis": ["up", "up", "down", None, "up", None]}


def stats(result: dict, label: str, ticker: str, horizon: int) -> dict:
    return result["axes"]["axis"][label]["assets"][ticker][str(horizon)]


def test_one_month_outcome_is_the_next_months_return_by_the_label_at_month_end() -> None:
    result = regime_performance(LABELS, M, RETURNS, horizons=(1,))

    up = stats(result, "up", "A", 1)  # labels Jan, Feb, May -> Feb, Mar, Jun returns
    assert up["n"] == 3
    assert up["mean"] == pytest.approx((0.10 - 0.02 + 0.01) / 3)
    assert up["median"] == pytest.approx(0.01)
    assert (up["min"], up["max"]) == (-0.02, 0.10)
    assert up["hit_rate"] == pytest.approx(2 / 3, abs=1e-4)


def test_multi_month_outcome_compounds_and_needs_the_whole_window() -> None:
    result = regime_performance(LABELS, M, RETURNS, horizons=(3,))

    up = stats(result, "up", "A", 3)  # Jan: Feb..Apr, Feb: Mar..May; May has no 3 months after
    assert up["n"] == 2
    assert up["mean"] == pytest.approx((1.1 * 0.98 * 1.04 - 1 + 0.98 * 1.04 * 1.05 - 1) / 2)
    assert up["independent"] == 0  # 2 outcomes // 3 months: overlapping windows
    assert "B" not in result["axes"]["axis"]["up"]["assets"]  # B misses March in both windows


def test_unknown_labels_are_skipped_and_all_uses_every_month_end() -> None:
    result = regime_performance(LABELS, M, RETURNS, horizons=(1,))

    assert set(result["axes"]["axis"]) == {"up", "down"}
    assert result["all"]["months"] == 6
    assert result["all"]["assets"]["A"]["1"]["n"] == 5  # the last month end has no next month
    assert result["horizons"] == [1]

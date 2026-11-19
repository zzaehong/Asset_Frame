from datetime import date

import pytest

from asset_frame.prediction.models import momentum_ranking, persistence_probability, random_ranking
from asset_frame.prediction.scoring import (
    brier,
    horizon_months,
    mean_with_mde,
    rank_ic,
    realized_returns,
    top_bottom_spread,
)

MONTHS = [date(2025 + (i // 12), i % 12 + 1, 28) for i in range(14)]


def test_momentum_ranks_by_the_eleven_months_before_the_latest_and_skips_incomplete() -> None:
    returns = {
        "UP": {m: 0.02 for m in MONTHS},
        "DOWN": {m: -0.01 for m in MONTHS},
        "SHORT": {m: 0.05 for m in MONTHS[-5:]},
        # a huge latest month must not count (the skipped month)
        "SPIKE": {**{m: 0.0 for m in MONTHS[:-1]}, MONTHS[-1]: 5.0},
    }

    ranking = momentum_ranking(returns, ["DOWN", "UP", "SHORT", "SPIKE"], MONTHS)

    assert ranking == ["UP", "SPIKE", "DOWN"]
    assert momentum_ranking(returns, ["UP"], MONTHS[:5]) == []


def test_random_ranking_is_fixed_by_the_date() -> None:
    tickers = list("ABCDEFGH")
    assert random_ranking(tickers, MONTHS[0]) == random_ranking(tickers, MONTHS[0])
    assert sorted(random_ranking(tickers, MONTHS[0])) == tickers
    assert persistence_probability(0.1) == 1.0
    assert persistence_probability(-0.1) == 0.0
    assert persistence_probability(None) is None


def test_horizon_needs_three_later_month_ends() -> None:
    assert horizon_months(MONTHS, MONTHS[10]) == tuple(MONTHS[11:14])
    assert horizon_months(MONTHS, MONTHS[11]) is None


def test_realized_returns_compound_and_drop_incomplete() -> None:
    returns = {"A": {MONTHS[0]: 0.10, MONTHS[1]: -0.10}, "B": {MONTHS[0]: 0.1}}
    result = realized_returns(returns, ["A", "B"], MONTHS[:2])
    assert result == {"A": pytest.approx(1.1 * 0.9 - 1)}


def test_rank_ic_spread_and_brier_hand_computed() -> None:
    order = ["A", "B", "C", "D", "E", "F"]
    perfect = {t: 0.06 - 0.01 * i for i, t in enumerate(order)}
    reversed_ = {t: 0.01 * i for i, t in enumerate(order)}

    assert rank_ic(order, perfect) == pytest.approx(1.0)
    assert rank_ic(order, reversed_) == pytest.approx(-1.0)
    # top 3 mean 0.05, bottom 3 mean 0.02 -> spread 0.03
    assert top_bottom_spread(order, perfect) == pytest.approx(0.03)
    assert rank_ic(order[:5], perfect) is None and top_bottom_spread(order[:5], perfect) is None
    assert rank_ic(order, {t: 0.01 for t in order}) is None
    assert brier(0.7, True) == pytest.approx(0.09)
    assert brier(1.0, False) == pytest.approx(1.0)


def test_mde_is_withheld_for_small_samples() -> None:
    assert mean_with_mde([0.1, 0.2, 0.3]) == (pytest.approx(0.2), None)
    mean, mde = mean_with_mde([0.1, 0.2, 0.3, 0.2, 0.2])
    assert mean == pytest.approx(0.2) and mde is not None and mde > 0


def _world():
    month_ends = [date(2020 + i // 12, i % 12 + 1, 28) for i in range(40)]
    tickers = [f"T{i:02d}" for i in range(10)] + ["SPY", "IEF"]
    returns = {f"T{i:02d}": {m: 0.001 * (i + 1) for m in month_ends} for i in range(10)}
    swing = {m: 0.01 * (-1) ** k for k, m in enumerate(month_ends)}
    returns["SPY"], returns["IEF"] = swing, dict(swing)  # correlation +1
    return month_ends, tickers, returns


def test_predictions_are_recorded_once_scored_after_three_months_and_summarised(tmp_path) -> None:
    from asset_frame.prediction.jobs import (
        record_human_prediction,
        record_predictions,
        score_due,
        scoreboard,
    )
    from asset_frame.storage.ledger import LedgerStore

    month_ends, anchors, returns = _world()
    ledger = LedgerStore(tmp_path / "db.sqlite3")
    known = month_ends[:37]  # decision at the 37th month end

    assert record_predictions(ledger, returns, anchors, known) == 2
    assert record_predictions(ledger, returns, anchors, known) == 0  # idempotent
    human = ["T09", "T08", "T07", "T00", "T01", "T02"]
    assert record_human_prediction(ledger, anchors, known, human, 0.3, "test") is True
    assert score_due(ledger, returns, known) == 0  # horizon not complete yet

    assert score_due(ledger, returns, month_ends) == 3
    assert score_due(ledger, returns, month_ends) == 0
    boards = {b.model: b for b in scoreboard(ledger)}
    assert boards["momentum_12_1"].mean_ic > 0.5
    assert boards["human"].mean_brier == pytest.approx(0.49)  # p=0.3, correlation stayed positive
    assert boards["momentum_12_1"].mean_brier == pytest.approx(0.0)
    assert boards["human"].ic_mde is None  # one sample


def test_human_prediction_rejects_bad_input(tmp_path) -> None:
    from asset_frame.prediction.jobs import record_human_prediction
    from asset_frame.storage.ledger import LedgerStore

    month_ends, anchors, _ = _world()
    ledger = LedgerStore(tmp_path / "db.sqlite3")
    good = anchors[:6]
    for ranking, probability in [
        (good[:5], 0.5),
        ([*good[:5], good[0]], 0.5),
        ([*good[:5], "NOPE"], 0.5),
        (good, 1.5),
    ]:
        with pytest.raises(ValueError):
            record_human_prediction(ledger, anchors, month_ends, ranking, probability, "n")
    assert ledger.entries() == ()

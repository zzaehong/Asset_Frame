import json
from datetime import date
from pathlib import Path

import pytest

from asset_frame.signal_log import (
    OBSERVATION,
    SCORE,
    macro_snapshot,
    record_signals,
    score_signals,
    scoreboard,
    state_on,
)
from asset_frame.storage.ledger import LedgerStore

STATE = {"votes": {"trend": 1}, "total": 2, "state": "buy", "conflict": False}


def chart(states):
    dates = [date(2026, 1, 30), date(2026, 2, 5), date(2026, 2, 27)]
    return {"dates": dates, "states": states}


def test_state_on_uses_the_last_trading_day_not_after_the_month_end() -> None:
    sell = {**STATE, "state": "sell"}
    c = chart([None, STATE, sell])
    assert state_on(c, date(2026, 2, 28)) == sell
    assert state_on(c, date(2026, 2, 10)) == STATE
    assert state_on(c, date(2026, 1, 15)) is None


def test_record_is_once_per_month_and_skips_assets_without_a_state(tmp_path: Path) -> None:
    ledger = LedgerStore(tmp_path / "l.sqlite3")
    charts = {"AAA": chart([None, STATE, STATE]), "BBB": chart([None, None, None])}
    assert record_signals(ledger, date(2026, 2, 28), charts, None) is True
    assert record_signals(ledger, date(2026, 2, 28), charts, None) is False
    payload = json.loads(ledger.entries()[0].payload)
    assert list(payload["chart"]) == ["AAA"] and payload["chart"]["AAA"]["state"] == "buy"
    assert ledger.entries()[0].entry_type == OBSERVATION


def months_after(start: int, count: int) -> list[date]:
    return [date(2026 + (start + i) // 12, (start + i) % 12 + 1, 28) for i in range(count)]


def test_chart_scoring_counts_hits_after_three_months_and_never_twice(tmp_path: Path) -> None:
    ledger = LedgerStore(tmp_path / "l.sqlite3")
    charts = {
        "UP": chart([STATE] * 3),
        "DN": chart([{**STATE, "state": "sell"}] * 3),
        "FLAT": chart([{**STATE, "state": "neutral"}] * 3),
        "BAD": chart([STATE] * 3),
    }
    record_signals(ledger, date(2026, 2, 28), charts, None)
    month_ends = months_after(2, 5)  # Mar..Jul 2026
    returns = {
        "UP": {m: 0.01 for m in month_ends},
        "DN": {m: -0.01 for m in month_ends},
        "FLAT": {m: 0.01 for m in month_ends},
        "BAD": {m: -0.02 for m in month_ends},
    }
    assert score_signals(ledger, {t: dict(v) for t, v in returns.items()}, month_ends[:2]) == 0
    assert score_signals(ledger, returns, month_ends) == 1  # chart only: macro absent
    assert score_signals(ledger, returns, month_ends) == 0
    board = scoreboard(ledger)["chart"]
    assert board == {"months": 1, "buy_n": 2, "buy_hits": 1, "sell_n": 1, "sell_hits": 1}
    score = json.loads(ledger.entries()[-1].payload)
    assert score["buy"]["mean"] == pytest.approx((1.01**3 - 1 + 0.98**3 - 1) / 2)
    assert ledger.entries()[-1].entry_type == SCORE


def test_macro_scoring_waits_six_months_and_reports_the_spread(tmp_path: Path) -> None:
    ledger = LedgerStore(tmp_path / "l.sqlite3")
    macro = {"strong": ["S"], "weak": ["W"], "warnings": {}}
    record_signals(ledger, date(2026, 2, 28), {}, macro)
    month_ends = months_after(2, 7)
    returns = {"S": {m: 0.02 for m in month_ends}, "W": {m: 0.0 for m in month_ends}}
    assert score_signals(ledger, returns, month_ends[:5]) == 1  # only the 3-month chart score
    assert score_signals(ledger, returns, month_ends) == 1  # now the 6-month macro score
    assert scoreboard(ledger)["macro"]["mean_spread"] == pytest.approx(1.02**6 - 1)


def test_macro_snapshot_reads_the_latest_label_and_warning_states() -> None:
    regime = {
        "rows": [{"quadrant": "old"}, {"quadrant": "up_up"}],
        "actions": {
            "axes": {
                "quadrant": {"up_up": {"strong": [{"ticker": "S"}], "weak": [{"ticker": "W"}]}}
            },
            "warnings": [{"key": "curve", "state": "warn"}, {"key": "policy", "state": "na"}],
        },
    }
    snap = macro_snapshot(regime)
    assert snap["strong"] == ["S"] and snap["weak"] == ["W"] and snap["warnings"]["curve"] == "warn"
    regime["rows"][-1]["quadrant"] = None
    assert macro_snapshot(regime)["strong"] == []

import sqlite3
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from asset_frame.ledger.chain import GENESIS_HASH, canonical_json, first_broken_seq
from asset_frame.regime.jobs import record_regime
from asset_frame.regime.replay import RegimeRow
from asset_frame.storage.ledger import LedgerStore

NOW = datetime(2026, 11, 19, tzinfo=UTC)


def ledger_with_three(tmp_path: Path) -> LedgerStore:
    ledger = LedgerStore(tmp_path / "db.sqlite3")
    for number in range(3):
        ledger.append("note", {"n": number, "b": 1}, now=NOW)
    return ledger


def test_entries_chain_from_genesis_and_verify(tmp_path: Path) -> None:
    entries = ledger_with_three(tmp_path).entries()

    assert [e.seq for e in entries] == [1, 2, 3]
    assert entries[0].prev_hash == GENESIS_HASH
    assert entries[1].prev_hash == entries[0].entry_hash
    assert first_broken_seq(entries) is None
    assert first_broken_seq(()) is None


def test_canonical_json_ignores_key_order() -> None:
    assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1}) == '{"a":2,"b":1}'


def test_tampering_is_detected_in_memory() -> None:
    from asset_frame.ledger.chain import Entry, compute_hash

    def make(seq: int, prev: str) -> Entry:
        return Entry(seq, "t", "{}", "x", prev, compute_hash(seq, prev, "t", "{}", "x"))

    first = make(1, GENESIS_HASH)
    second = make(2, first.entry_hash)
    assert first_broken_seq((first, second)) is None
    assert first_broken_seq((replace(first, payload='{"a":1}'), second)) == 1  # edited
    assert first_broken_seq((second,)) == 2  # first entry removed
    assert first_broken_seq((first, make(3, first.entry_hash))) == 3  # gap in seq


def test_database_refuses_update_and_delete(tmp_path: Path) -> None:
    ledger_with_three(tmp_path)
    with sqlite3.connect(tmp_path / "db.sqlite3") as connection:
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            connection.execute("UPDATE ledger_entry SET payload = '{}' WHERE seq = 1")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            connection.execute("DELETE FROM ledger_entry WHERE seq = 2")


def test_duplicate_key_appends_nothing(tmp_path: Path) -> None:
    ledger = LedgerStore(tmp_path / "db.sqlite3")

    assert ledger.append("note", {"n": 1}, key="k", now=NOW) is not None
    assert ledger.append("note", {"n": 2}, key="k", now=NOW) is None
    assert [e.payload for e in ledger.entries()] == ['{"n":1}']


def regime_row(month: int) -> RegimeRow:
    return RegimeRow(date(2026, month, 28), 0.1, 0.02, 0.0, False, False, None, 0.3, None, False)


def test_record_regime_live_is_idempotent_and_replay_is_separate(tmp_path: Path) -> None:
    ledger = LedgerStore(tmp_path / "db.sqlite3")
    rows = (regime_row(8), regime_row(9))

    assert record_regime(ledger, rows, replay_all=False) == (1, 0)
    assert record_regime(ledger, rows, replay_all=False) == (0, 1)
    assert record_regime(ledger, rows, replay_all=True) == (2, 0)  # same months, kind replay
    assert record_regime(ledger, rows, replay_all=True) == (0, 2)
    entries = ledger.entries()
    assert len(entries) == 3 and first_broken_seq(entries) is None
    assert '"kind":"live"' in entries[0].payload and "2026-09-28" in entries[0].payload

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from asset_frame.ledger.chain import GENESIS_HASH, Entry, canonical_json, compute_hash

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ledger_entry (
    seq INTEGER PRIMARY KEY,
    entry_type TEXT NOT NULL,
    entry_key TEXT UNIQUE,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    entry_hash TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS ledger_entry_no_update BEFORE UPDATE ON ledger_entry
BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER IF NOT EXISTS ledger_entry_no_delete BEFORE DELETE ON ledger_entry
BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
"""


class LedgerStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._path, isolation_level=None)  # explicit transactions
        try:
            yield connection
        finally:
            connection.close()

    def append(
        self,
        entry_type: str,
        payload: object,
        *,
        key: str | None = None,
        now: datetime | None = None,
    ) -> Entry | None:
        """Append one entry; returns None (nothing written) if `key` is already in the ledger."""
        created_at = (now or datetime.now(UTC)).isoformat()
        body = canonical_json(payload)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")  # serialises writers so seq and prev_hash agree
            try:
                if (
                    key is not None
                    and connection.execute(
                        "SELECT 1 FROM ledger_entry WHERE entry_key = ?", (key,)
                    ).fetchone()
                ):
                    connection.execute("ROLLBACK")
                    return None
                last = connection.execute(
                    "SELECT seq, entry_hash FROM ledger_entry ORDER BY seq DESC LIMIT 1"
                ).fetchone()
                seq, prev_hash = (1, GENESIS_HASH) if last is None else (last[0] + 1, last[1])
                entry_hash = compute_hash(seq, prev_hash, entry_type, body, created_at)
                connection.execute(
                    "INSERT INTO ledger_entry VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (seq, entry_type, key, body, created_at, prev_hash, entry_hash),
                )
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise
        return Entry(seq, entry_type, body, created_at, prev_hash, entry_hash)

    def entries(self) -> tuple[Entry, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT seq, entry_type, payload, created_at, prev_hash, entry_hash "
                "FROM ledger_entry ORDER BY seq"
            ).fetchall()
        return tuple(Entry(*row) for row in rows)

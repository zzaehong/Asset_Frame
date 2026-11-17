from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from asset_frame.domain.models import (
    Asset,
    AssetIdentifier,
    AssetType,
    CorporateAction,
    IdentifierType,
    PriceObservation,
    QuarantinedPrice,
    RawSnapshot,
    SourceDefinition,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    authority TEXT NOT NULL,
    authority_type TEXT NOT NULL,
    access_method TEXT NOT NULL,
    source_role TEXT NOT NULL,
    data_kinds TEXT NOT NULL,
    documentation_url TEXT NOT NULL,
    terms_url TEXT NOT NULL,
    verification_url TEXT NOT NULL,
    enabled INTEGER NOT NULL,
    implementation_status TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    ingestion_run_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    data_kind TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('started', 'succeeded', 'failed')),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    records_received INTEGER NOT NULL DEFAULT 0 CHECK (records_received >= 0),
    records_accepted INTEGER NOT NULL DEFAULT 0 CHECK (records_accepted >= 0),
    records_quarantined INTEGER NOT NULL DEFAULT 0 CHECK (records_quarantined >= 0),
    error_code TEXT,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS raw_snapshots (
    raw_snapshot_id TEXT PRIMARY KEY,
    ingestion_run_id TEXT REFERENCES ingestion_runs(ingestion_run_id),
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    request_url TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    http_status INTEGER NOT NULL,
    content_type TEXT,
    content_length INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    storage_path TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assets (
    asset_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    country_code TEXT NOT NULL,
    currency TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS asset_identifiers (
    asset_id TEXT NOT NULL REFERENCES assets(asset_id),
    identifier_type TEXT NOT NULL,
    identifier_value TEXT NOT NULL,
    valid_from TEXT,
    valid_to TEXT,
    PRIMARY KEY (asset_id, identifier_type, identifier_value)
);

-- Point-in-time: re-collected (asset, date, source) rows are appended as new versions,
-- never updated. Readers pick a version by fetched_at.
CREATE TABLE IF NOT EXISTS price_observations (
    price_version_id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id TEXT NOT NULL REFERENCES assets(asset_id),
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    raw_snapshot_id TEXT NOT NULL REFERENCES raw_snapshots(raw_snapshot_id),
    trading_date TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    currency TEXT NOT NULL,
    open TEXT,
    high TEXT,
    low TEXT,
    close TEXT NOT NULL,
    adjusted_close TEXT,
    volume TEXT,
    price_basis TEXT NOT NULL,
    quality_status TEXT NOT NULL,
    UNIQUE (asset_id, source_id, trading_date, price_basis, raw_snapshot_id)
);
CREATE INDEX IF NOT EXISTS price_observations_lookup_idx
    ON price_observations (asset_id, source_id, trading_date, fetched_at);

CREATE TABLE IF NOT EXISTS corporate_actions (
    corporate_action_id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id TEXT NOT NULL REFERENCES assets(asset_id),
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    raw_snapshot_id TEXT NOT NULL REFERENCES raw_snapshots(raw_snapshot_id),
    action_type TEXT NOT NULL,
    effective_at TEXT NOT NULL,
    announced_at TEXT,
    amount TEXT,
    currency TEXT,
    ratio_numerator TEXT,
    ratio_denominator TEXT,
    metadata TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS price_quarantine (
    quarantine_id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    raw_snapshot_id TEXT NOT NULL REFERENCES raw_snapshots(raw_snapshot_id),
    trading_date TEXT NOT NULL,
    issue_code TEXT NOT NULL,
    details TEXT NOT NULL,
    detected_at TEXT NOT NULL
);
"""


class SqliteIngestionRepository:
    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:
                yield connection
        finally:
            connection.close()

    def upsert_source(self, source: SourceDefinition) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (source_id) DO UPDATE SET
                    authority = excluded.authority,
                    authority_type = excluded.authority_type,
                    access_method = excluded.access_method,
                    source_role = excluded.source_role,
                    data_kinds = excluded.data_kinds,
                    documentation_url = excluded.documentation_url,
                    terms_url = excluded.terms_url,
                    verification_url = excluded.verification_url,
                    enabled = excluded.enabled,
                    implementation_status = excluded.implementation_status,
                    updated_at = excluded.updated_at
                """,
                (
                    source.id,
                    source.authority,
                    source.authority_type.value,
                    source.access_method.value,
                    source.role.value,
                    json.dumps([kind.value for kind in source.data_kinds]),
                    source.documentation_url,
                    source.terms_url,
                    source.verification_url,
                    int(source.enabled),
                    source.implementation_status.value,
                    _now(),
                ),
            )

    def start_ingestion_run(self, *, source_id: str, data_kind: str) -> UUID:
        run_id = uuid4()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO ingestion_runs (
                    ingestion_run_id, source_id, data_kind, status, started_at
                ) VALUES (?, ?, ?, 'started', ?)
                """,
                (str(run_id), source_id, data_kind, _now()),
            )
        return run_id

    def complete_ingestion_run(
        self,
        run_id: UUID,
        *,
        records_received: int,
        records_accepted: int,
        records_quarantined: int,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE ingestion_runs SET status = 'succeeded', finished_at = ?,
                    records_received = ?, records_accepted = ?, records_quarantined = ?
                WHERE ingestion_run_id = ?
                """,
                (_now(), records_received, records_accepted, records_quarantined, str(run_id)),
            )

    def fail_ingestion_run(self, run_id: UUID, *, error_code: str, error_message: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE ingestion_runs SET status = 'failed', finished_at = ?,
                    error_code = ?, error_message = ?
                WHERE ingestion_run_id = ?
                """,
                (_now(), error_code, error_message, str(run_id)),
            )

    def save_raw_snapshot(self, snapshot: RawSnapshot) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO raw_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (raw_snapshot_id) DO NOTHING
                """,
                (
                    str(snapshot.id),
                    _text(snapshot.ingestion_run_id),
                    snapshot.source_id,
                    snapshot.request_url,
                    snapshot.fetched_at.isoformat(),
                    snapshot.http_status,
                    snapshot.content_type,
                    snapshot.content_length,
                    snapshot.sha256,
                    snapshot.storage_path,
                ),
            )

    def upsert_assets(
        self, assets: tuple[Asset, ...], identifiers: tuple[AssetIdentifier, ...]
    ) -> None:
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO assets VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (asset_id) DO UPDATE SET
                    name = excluded.name,
                    asset_type = excluded.asset_type,
                    country_code = excluded.country_code,
                    currency = excluded.currency
                """,
                [
                    (str(a.id), a.name, a.asset_type.value, a.country_code, a.currency)
                    for a in assets
                ],
            )
            connection.executemany(
                "INSERT INTO asset_identifiers VALUES (?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
                [_identifier_row(identifier) for identifier in identifiers],
            )

    def list_assets(self, *, country_code: str) -> tuple[Asset, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT asset_id, name, asset_type, country_code, currency
                FROM assets WHERE country_code = ? ORDER BY asset_id
                """,
                (country_code,),
            ).fetchall()
        return tuple(
            Asset(
                id=UUID(row[0]),
                name=row[1],
                asset_type=AssetType(row[2]),
                country_code=row[3],
                currency=row[4],
            )
            for row in rows
        )

    def list_asset_identifiers(
        self, *, country_code: str, identifier_type: IdentifierType
    ) -> tuple[AssetIdentifier, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT ai.asset_id, ai.identifier_type, ai.identifier_value,
                       ai.valid_from, ai.valid_to
                FROM asset_identifiers AS ai
                JOIN assets AS a ON a.asset_id = ai.asset_id
                WHERE a.country_code = ? AND ai.identifier_type = ? AND ai.valid_to IS NULL
                ORDER BY ai.asset_id, ai.identifier_value
                """,
                (country_code, identifier_type.value),
            ).fetchall()
        return tuple(
            AssetIdentifier(
                asset_id=UUID(row[0]),
                identifier_type=IdentifierType(row[1]),
                value=row[2],
                valid_from=None if row[3] is None else date.fromisoformat(row[3]),
                valid_to=None if row[4] is None else date.fromisoformat(row[4]),
            )
            for row in rows
        )

    def save_prices(self, prices: tuple[PriceObservation, ...]) -> None:
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO price_observations (
                    asset_id, source_id, raw_snapshot_id, trading_date, fetched_at, currency,
                    open, high, low, close, adjusted_close, volume, price_basis, quality_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(price.asset_id),
                        price.source_id,
                        str(price.raw_snapshot_id),
                        price.trading_date.isoformat(),
                        price.fetched_at.isoformat(),
                        price.currency,
                        _text(price.open),
                        _text(price.high),
                        _text(price.low),
                        str(price.close),
                        _text(price.adjusted_close),
                        _text(price.volume),
                        price.price_basis,
                        price.quality_status.value,
                    )
                    for price in prices
                ],
            )

    def save_corporate_actions(self, actions: tuple[CorporateAction, ...]) -> None:
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO corporate_actions (
                    asset_id, source_id, raw_snapshot_id, action_type, effective_at,
                    announced_at, amount, currency, ratio_numerator, ratio_denominator, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(action.asset_id),
                        action.source_id,
                        str(action.raw_snapshot_id),
                        action.action_type,
                        action.effective_at.isoformat(),
                        None if action.announced_at is None else action.announced_at.isoformat(),
                        _text(action.amount),
                        action.currency,
                        _text(action.ratio_numerator),
                        _text(action.ratio_denominator),
                        json.dumps(action.metadata, default=str),
                    )
                    for action in actions
                ],
            )

    def save_quarantined_prices(self, prices: tuple[QuarantinedPrice, ...]) -> None:
        detected_at = _now()
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO price_quarantine (
                    asset_id, source_id, raw_snapshot_id, trading_date, issue_code, details,
                    detected_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(item.price.asset_id),
                        item.price.source_id,
                        str(item.price.raw_snapshot_id),
                        item.price.trading_date.isoformat(),
                        item.issue_code,
                        json.dumps(item.details, default=str),
                        detected_at,
                    )
                    for item in prices
                ],
            )


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _text(value: Decimal | UUID | None) -> str | None:
    return None if value is None else str(value)


def _identifier_row(identifier: AssetIdentifier) -> tuple[str | None, ...]:
    return (
        str(identifier.asset_id),
        identifier.identifier_type.value,
        identifier.value,
        None if identifier.valid_from is None else identifier.valid_from.isoformat(),
        None if identifier.valid_to is None else identifier.valid_to.isoformat(),
    )

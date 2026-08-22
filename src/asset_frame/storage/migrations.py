from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import psycopg

_SENTINELS = {
    "001_core.sql": "assets",
    "002_analysis_universe.sql": "analysis_universe_runs",
    "003_market_data_jobs.sql": "market_data_jobs",
    "004_krx_backfill_jobs.sql": "krx_backfill_jobs",
    "005_fundamentals_and_news.sql": "news_articles",
    "006_universe_collection_jobs.sql": "universe_collection_jobs",
    "007_complete_ohlc.sql": None,
}


@dataclass(frozen=True, slots=True)
class MigrationResult:
    applied: tuple[str, ...]
    baselined: tuple[str, ...]
    already_applied: tuple[str, ...]


def migrate_database(database_url: str, migrations_path: Path) -> MigrationResult:
    files = tuple(sorted(migrations_path.glob("[0-9][0-9][0-9]_*.sql")))
    if not files:
        raise ValueError("no database migrations were found")
    applied: list[str] = []
    baselined: list[str] = []
    already_applied: list[str] = []
    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version text PRIMARY KEY,
                sha256 char(64) NOT NULL,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        for path in files:
            version = path.name
            script = path.read_text(encoding="utf-8")
            checksum = sha256(script.encode()).hexdigest()
            cursor.execute("SELECT sha256 FROM schema_migrations WHERE version = %s", (version,))
            row = cursor.fetchone()
            if row is not None:
                if row[0] != checksum:
                    raise RuntimeError(f"applied migration checksum changed: {version}")
                already_applied.append(version)
                continue
            sentinel = _SENTINELS.get(version)
            if sentinel is not None and _table_exists(cursor, sentinel):
                _record(cursor, version, checksum)
                baselined.append(version)
                continue
            cursor.execute(script)
            _record(cursor, version, checksum)
            applied.append(version)
    return MigrationResult(tuple(applied), tuple(baselined), tuple(already_applied))


def _table_exists(cursor: psycopg.Cursor[tuple[object, ...]], table_name: str) -> bool:
    cursor.execute("SELECT to_regclass(%s)", (f"public.{table_name}",))
    row = cursor.fetchone()
    return row is not None and row[0] is not None


def _record(cursor: psycopg.Cursor[tuple[object, ...]], version: str, checksum: str) -> None:
    cursor.execute(
        "INSERT INTO schema_migrations (version, sha256) VALUES (%s, %s)",
        (version, checksum),
    )

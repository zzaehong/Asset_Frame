import os
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest

from asset_frame.sources.registry import load_source_registry
from asset_frame.storage.postgres import PostgresIngestionRepository
from asset_frame.storage.universe_v2 import PostgresUniverseV2Repository


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL is not configured")
def test_postgres_reserves_monthly_provider_symbols_without_exceeding_limit() -> None:
    database_url = os.environ["DATABASE_URL"]

    @contextmanager
    def connection_factory():  # type: ignore[no-untyped-def]
        with psycopg.connect(database_url) as connection:
            yield connection

    source = next(
        item
        for item in load_source_registry(Path("config/sources.toml"))
        if item.id == "tiingo-eod"
    )
    PostgresIngestionRepository(connection_factory).upsert_source(source)
    repository = PostgresUniverseV2Repository(connection_factory)
    used_at = datetime(1901, 1, 15, 12, tzinfo=UTC)

    try:
        first = repository.reserve_monthly_symbol(
            source_id=source.id,
            symbol="aapl",
            used_at=used_at,
            unique_symbol_limit=1,
        )
        repeated = repository.reserve_monthly_symbol(
            source_id=source.id,
            symbol="AAPL",
            used_at=used_at,
            unique_symbol_limit=1,
        )
        rejected = repository.reserve_monthly_symbol(
            source_id=source.id,
            symbol="MSFT",
            used_at=used_at,
            unique_symbol_limit=1,
        )

        assert first.accepted is True
        assert first.already_reserved is False
        assert first.unique_symbol_count == 1
        assert repeated.accepted is True
        assert repeated.already_reserved is True
        assert repeated.unique_symbol_count == 1
        assert rejected.accepted is False
        assert rejected.unique_symbol_count == 1

        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT symbol, request_count
                FROM provider_monthly_symbol_usage
                WHERE source_id = %s AND usage_month = DATE '1901-01-01'
                """,
                (source.id,),
            )
            assert cursor.fetchall() == [("AAPL", 2)]
    finally:
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM provider_monthly_symbol_usage
                WHERE source_id = %s AND usage_month = DATE '1901-01-01'
                """,
                (source.id,),
            )

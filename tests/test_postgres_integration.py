import os
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from asset_frame.domain.models import (
    Asset,
    AssetIdentifier,
    AssetType,
    CorporateAction,
    IdentifierType,
    PriceObservation,
    RawSnapshot,
)
from asset_frame.sources.registry import load_source_registry
from asset_frame.storage.postgres import PostgresIngestionRepository


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL is not configured")
def test_postgres_schema_and_source_repository() -> None:
    database_url = os.environ["DATABASE_URL"]

    @contextmanager
    def connection_factory():  # type: ignore[no-untyped-def]
        with psycopg.connect(database_url) as connection:
            yield connection

    source = load_source_registry(Path("config/sources.toml"))[0]
    repository = PostgresIngestionRepository(connection_factory)
    repository.upsert_source(source)

    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT authority, access_method, implementation_status
            FROM sources
            WHERE source_id = %s
            """,
            (source.id,),
        )
        assert cursor.fetchone() == (
            source.authority,
            source.access_method.value,
            source.implementation_status.value,
        )
        cursor.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"
        )
        assert cursor.fetchone()[0] >= 10


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL is not configured")
def test_postgres_saves_tiingo_price_and_corporate_action() -> None:
    database_url = os.environ["DATABASE_URL"]

    @contextmanager
    def connection_factory():  # type: ignore[no-untyped-def]
        with psycopg.connect(database_url) as connection:
            yield connection

    source = next(
        source
        for source in load_source_registry(Path("config/sources.toml"))
        if source.id == "tiingo-eod"
    )
    repository = PostgresIngestionRepository(connection_factory)
    repository.upsert_source(source)
    asset_id = uuid4()
    snapshot_id = uuid4()
    fetched_at = datetime(2026, 8, 21, tzinfo=UTC)
    repository.upsert_assets(
        (Asset(asset_id, "Integration Test Asset", AssetType.EQUITY, "US", "USD"),),
        (AssetIdentifier(asset_id, IdentifierType.TICKER, f"TEST-{asset_id.hex[:8]}"),),
    )
    repository.save_raw_snapshot(
        RawSnapshot(
            snapshot_id,
            source.id,
            "https://api.tiingo.com/tiingo/daily/TEST/prices",
            fetched_at,
            200,
            "application/json",
            2,
            "0" * 64,
            "tiingo/test.bin",
        )
    )
    repository.save_prices(
        (
            PriceObservation(
                asset_id,
                source.id,
                snapshot_id,
                date(2026, 8, 20),
                "USD",
                Decimal("100"),
                Decimal("102"),
                Decimal("99"),
                Decimal("101"),
                Decimal("100.5"),
                Decimal("1000"),
                fetched_at,
                "raw_with_crsp_adjusted_close",
            ),
        )
    )
    repository.save_corporate_actions(
        (
            CorporateAction(
                asset_id,
                source.id,
                snapshot_id,
                "cash_dividend",
                date(2026, 8, 20),
                None,
                amount=Decimal("0.25"),
                currency="USD",
            ),
        )
    )

    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT close, adjusted_close FROM price_observations WHERE asset_id = %s",
            (asset_id,),
        )
        assert cursor.fetchone() == (Decimal("101"), Decimal("100.5"))
        cursor.execute(
            "SELECT action_type, amount FROM corporate_actions WHERE asset_id = %s",
            (asset_id,),
        )
        assert cursor.fetchone() == ("cash_dividend", Decimal("0.25"))

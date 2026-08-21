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


@pytest.fixture
def postgres_cleanup():  # type: ignore[no-untyped-def]
    tracked: dict[str, list[object]] = {
        "asset_ids": [],
        "snapshot_ids": [],
        "run_ids": [],
    }
    yield tracked
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return
    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        if tracked["asset_ids"]:
            cursor.execute(
                "DELETE FROM corporate_actions WHERE asset_id = ANY(%s)",
                (tracked["asset_ids"],),
            )
            cursor.execute(
                "DELETE FROM price_observations WHERE asset_id = ANY(%s)",
                (tracked["asset_ids"],),
            )
            cursor.execute(
                "DELETE FROM asset_identifiers WHERE asset_id = ANY(%s)",
                (tracked["asset_ids"],),
            )
            cursor.execute("DELETE FROM assets WHERE asset_id = ANY(%s)", (tracked["asset_ids"],))
        if tracked["snapshot_ids"]:
            cursor.execute(
                "DELETE FROM raw_snapshots WHERE raw_snapshot_id = ANY(%s)",
                (tracked["snapshot_ids"],),
            )
        if tracked["run_ids"]:
            cursor.execute(
                "DELETE FROM ingestion_runs WHERE ingestion_run_id = ANY(%s)",
                (tracked["run_ids"],),
            )


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
def test_postgres_tracks_ingestion_run_and_snapshot_lineage(postgres_cleanup) -> None:  # type: ignore[no-untyped-def]
    database_url = os.environ["DATABASE_URL"]

    @contextmanager
    def connection_factory():  # type: ignore[no-untyped-def]
        with psycopg.connect(database_url) as connection:
            yield connection

    source = load_source_registry(Path("config/sources.toml"))[0]
    repository = PostgresIngestionRepository(connection_factory)
    repository.upsert_source(source)
    run_id = repository.start_ingestion_run(source_id=source.id, data_kind="integration_test")
    snapshot_id = uuid4()
    postgres_cleanup["run_ids"].append(run_id)
    postgres_cleanup["snapshot_ids"].append(snapshot_id)
    repository.save_raw_snapshot(
        RawSnapshot(
            snapshot_id,
            source.id,
            "https://example.test/integration",
            datetime.now(UTC),
            200,
            "application/json",
            2,
            "1" * 64,
            f"integration/{snapshot_id}.bin",
            run_id,
        )
    )
    repository.complete_ingestion_run(
        run_id,
        records_received=2,
        records_accepted=1,
        records_quarantined=1,
    )

    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT status, records_received, records_accepted, records_quarantined
            FROM ingestion_runs WHERE ingestion_run_id = %s
            """,
            (run_id,),
        )
        assert cursor.fetchone() == ("succeeded", 2, 1, 1)
        cursor.execute(
            "SELECT ingestion_run_id FROM raw_snapshots WHERE raw_snapshot_id = %s",
            (snapshot_id,),
        )
        assert cursor.fetchone() == (run_id,)
    assert (
        repository.latest_successful_run(source_id=source.id, data_kind="integration_test")
        is not None
    )


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL is not configured")
def test_postgres_saves_tiingo_price_and_corporate_action(postgres_cleanup) -> None:  # type: ignore[no-untyped-def]
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
    postgres_cleanup["asset_ids"].append(asset_id)
    postgres_cleanup["snapshot_ids"].append(snapshot_id)
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

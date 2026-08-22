import os
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from asset_frame.domain.models import (
    Asset,
    AssetIdentifier,
    AssetType,
    IdentifierType,
    PriceObservation,
    RawSnapshot,
)
from asset_frame.ingestion.universe import UniversePolicy, select_analysis_universe
from asset_frame.sources.registry import load_source_registry
from asset_frame.storage.postgres import PostgresIngestionRepository
from asset_frame.storage.universe import PostgresUniverseRepository


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL is not configured")
def test_postgres_selects_and_saves_analysis_universe() -> None:
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
    ingestion = PostgresIngestionRepository(connection_factory)
    universe = PostgresUniverseRepository(connection_factory)
    ingestion.upsert_source(source)
    asset_ids = (uuid4(), uuid4())
    snapshot_id = uuid4()
    as_of = date(2026, 8, 21)
    fetched_at = datetime(2026, 8, 21, tzinfo=UTC)
    ingestion.upsert_assets(
        tuple(
            Asset(item, f"Asset {index}", AssetType.EQUITY, "US", "USD")
            for index, item in enumerate(asset_ids)
        ),
        tuple(
            AssetIdentifier(item, IdentifierType.TICKER, ticker)
            for item, ticker in zip(asset_ids, ("PINNED", "LIQUID"), strict=True)
        ),
    )
    ingestion.save_raw_snapshot(
        RawSnapshot(
            snapshot_id,
            source.id,
            "https://example.test/prices",
            fetched_at,
            200,
            "application/json",
            2,
            "2" * 64,
            "integration/universe.bin",
        )
    )
    ingestion.save_prices(
        tuple(
            PriceObservation(
                asset_id,
                source.id,
                snapshot_id,
                as_of - timedelta(days=offset),
                "USD",
                Decimal("1"),
                Decimal("1"),
                Decimal("1"),
                Decimal("1"),
                Decimal("1"),
                volume,
                fetched_at,
                "raw_with_crsp_adjusted_close",
            )
            for asset_id, volume in zip(asset_ids, (Decimal("1"), Decimal("100")), strict=True)
            for offset in (0, 1)
        )
    )

    try:
        candidates = universe.liquidity_candidates(
            country_code="US",
            as_of_date=as_of,
            lookback_observations=2,
            pinned_tickers=frozenset({"PINNED"}),
        )
        selection = select_analysis_universe(
            country_code="US",
            as_of_date=as_of,
            candidates=candidates,
            policy=UniversePolicy(1, 1, 2, 2, Decimal("10")),
        )
        run_id = universe.save_selection(selection, UniversePolicy(1, 1, 2, 2, Decimal("10")))
        assert [item.ticker for item in selection.memberships] == ["PINNED"]
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM analysis_universe_memberships "
                "WHERE analysis_universe_run_id = %s",
                (run_id,),
            )
            assert cursor.fetchone() == (1,)
    finally:
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM analysis_universe_runs WHERE country_code = 'US' AND as_of_date = %s",
                (as_of,),
            )
            cursor.execute(
                "DELETE FROM price_observations WHERE asset_id = ANY(%s)", (list(asset_ids),)
            )
            cursor.execute(
                "DELETE FROM asset_identifiers WHERE asset_id = ANY(%s)", (list(asset_ids),)
            )
            cursor.execute("DELETE FROM assets WHERE asset_id = ANY(%s)", (list(asset_ids),))
            cursor.execute("DELETE FROM raw_snapshots WHERE raw_snapshot_id = %s", (snapshot_id,))

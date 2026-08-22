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
    AssetType,
    FinancialFact,
    NewsArticleMention,
    RawSnapshot,
)
from asset_frame.sources.registry import load_source_registry
from asset_frame.storage.postgres import PostgresIngestionRepository


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL is not configured")
def test_postgres_financial_fact_and_news_are_idempotent() -> None:
    database_url = os.environ["DATABASE_URL"]

    @contextmanager
    def connection_factory():  # type: ignore[no-untyped-def]
        with psycopg.connect(database_url) as connection:
            yield connection

    repository = PostgresIngestionRepository(connection_factory)
    sources = {item.id: item for item in load_source_registry(Path("config/sources.toml"))}
    repository.upsert_source(sources["sec-edgar-submissions"])
    repository.upsert_source(sources["gdelt-doc"])
    asset_id = uuid4()
    fact_snapshot_id = uuid4()
    news_snapshot_id = uuid4()
    repository.upsert_assets(
        (Asset(asset_id, "Integration Asset", AssetType.EQUITY, "US", "USD"),), ()
    )
    fetched_at = datetime(2099, 1, 2, tzinfo=UTC)
    for snapshot_id, source_id in (
        (fact_snapshot_id, "sec-edgar-submissions"),
        (news_snapshot_id, "gdelt-doc"),
    ):
        repository.save_raw_snapshot(
            RawSnapshot(
                snapshot_id,
                source_id,
                f"https://example.test/{snapshot_id}",
                fetched_at,
                200,
                "application/json",
                1,
                snapshot_id.hex.ljust(64, "0"),
                f"integration/{snapshot_id}.bin",
            )
        )
    fact = FinancialFact(
        asset_id,
        "sec-edgar-submissions",
        fact_snapshot_id,
        "us-gaap",
        "Assets",
        "USD",
        Decimal("100"),
        None,
        date(2098, 12, 31),
        fetched_at,
        None,
        None,
        "integration-accession",
        {"form": "10-K"},
    )
    mention = NewsArticleMention(
        asset_id,
        "gdelt-doc",
        news_snapshot_id,
        f"https://example.test/news/{asset_id}",
        "Integration headline",
        "example.test",
        "English",
        "United States",
        fetched_at,
        fetched_at,
        '"Integration Asset"',
    )
    try:
        repository.save_financial_facts((fact,))
        repository.save_financial_facts((fact,))
        repository.save_news_mentions((mention,))
        repository.save_news_mentions((mention,))
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM financial_facts WHERE asset_id = %s", (asset_id,))
            assert cursor.fetchone() == (1,)
            cursor.execute(
                "SELECT count(*) FROM news_asset_mentions WHERE asset_id = %s", (asset_id,)
            )
            assert cursor.fetchone() == (1,)
    finally:
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM news_asset_mentions WHERE asset_id = %s", (asset_id,))
            cursor.execute("DELETE FROM news_articles WHERE news_article_id = %s", (mention.id,))
            cursor.execute("DELETE FROM financial_facts WHERE asset_id = %s", (asset_id,))
            cursor.execute("DELETE FROM assets WHERE asset_id = %s", (asset_id,))
            cursor.execute(
                "DELETE FROM raw_snapshots WHERE raw_snapshot_id = ANY(%s)",
                ([fact_snapshot_id, news_snapshot_id],),
            )

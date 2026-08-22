import os
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from asset_frame.domain.models import Asset, AssetType
from asset_frame.sources.registry import load_source_registry
from asset_frame.storage.collection_batch import (
    PostgresUniverseCollectionRepository,
    UniverseCollectionItem,
)
from asset_frame.storage.postgres import PostgresIngestionRepository


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL is not configured")
def test_postgres_universe_collection_job_resumes_failed_asset() -> None:
    database_url = os.environ["DATABASE_URL"]

    @contextmanager
    def connection_factory():  # type: ignore[no-untyped-def]
        with psycopg.connect(database_url) as connection:
            yield connection

    source = next(
        item for item in load_source_registry(Path("config/sources.toml")) if item.id == "gdelt-doc"
    )
    ingestion = PostgresIngestionRepository(connection_factory)
    ingestion.upsert_source(source)
    asset_ids = (uuid4(), uuid4())
    ingestion.upsert_assets(
        tuple(
            Asset(asset_id, f"Collection Asset {index}", AssetType.EQUITY, "US", "USD")
            for index, asset_id in enumerate(asset_ids)
        ),
        (),
    )
    repository = PostgresUniverseCollectionRepository(connection_factory)
    job_id = repository.prepare_job(
        source_id=source.id,
        job_type="gdelt_news",
        country_code="US",
        as_of_date=date(2099, 9, 1),
        start_date=date(2099, 8, 1),
        end_date=date(2099, 9, 1),
        max_news_records=25,
        items=tuple(
            UniverseCollectionItem(asset_id, f"TEST{index}", search_query=f'"TEST{index}"')
            for index, asset_id in enumerate(asset_ids)
        ),
    )
    try:
        claimed = repository.claim_items(job_id=job_id, limit=2, retry_failed=False)
        repository.complete_item(job_id=job_id, item=claimed[0], records_accepted=0)
        repository.fail_item(job_id=job_id, item=claimed[1], error_message="rate limited")
        repository.refresh_job_status(job_id)
        progress = repository.job_progress(job_id)
        assert (progress.no_data, progress.failed, progress.job.status) == (
            1,
            1,
            "completed_with_errors",
        )

        retried = repository.claim_items(job_id=job_id, limit=1, retry_failed=True)
        assert retried == (claimed[1],)
        repository.complete_item(job_id=job_id, item=retried[0], records_accepted=3)
        repository.refresh_job_status(job_id)
        assert repository.get_job(job_id).status == "completed"
    finally:
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM universe_collection_jobs WHERE universe_collection_job_id = %s",
                (job_id,),
            )
            cursor.execute("DELETE FROM assets WHERE asset_id = ANY(%s)", (list(asset_ids),))

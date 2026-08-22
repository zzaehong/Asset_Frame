import os
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import psycopg
import pytest

from asset_frame.connectors.krx import KrxDataset
from asset_frame.sources.registry import load_source_registry
from asset_frame.storage.krx_batch import KrxBackfillItem, PostgresKrxBatchRepository
from asset_frame.storage.postgres import PostgresIngestionRepository


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL is not configured")
def test_postgres_krx_job_tracks_no_data_and_retry() -> None:
    database_url = os.environ["DATABASE_URL"]

    @contextmanager
    def connection_factory():  # type: ignore[no-untyped-def]
        with psycopg.connect(database_url) as connection:
            yield connection

    source = next(
        item
        for item in load_source_registry(Path("config/sources.toml"))
        if item.id == "krx-open-api"
    )
    PostgresIngestionRepository(connection_factory).upsert_source(source)
    repository = PostgresKrxBatchRepository(connection_factory)
    items = (
        KrxBackfillItem(date(2026, 8, 20), KrxDataset.KOSPI_PRICES),
        KrxBackfillItem(date(2026, 8, 20), KrxDataset.ETF_PRICES),
        KrxBackfillItem(date(2026, 8, 21), KrxDataset.KOSDAQ_PRICES),
    )
    job_id = repository.prepare_job(
        source_id=source.id,
        as_of_date=date(2026, 8, 21),
        start_date=date(2026, 8, 20),
        end_date=date(2026, 8, 21),
        items=items,
    )
    try:
        claimed = repository.claim_items(job_id=job_id, limit=3, retry_failed=False)
        repository.complete_item(job_id=job_id, item=claimed[0], records_accepted=100)
        repository.complete_item(job_id=job_id, item=claimed[1], records_accepted=0)
        repository.fail_item(job_id=job_id, item=claimed[2], error_message="temporary")
        repository.refresh_job_status(job_id)

        progress = repository.job_progress(job_id)
        assert progress.job.status == "completed_with_errors"
        assert (progress.total, progress.succeeded, progress.no_data, progress.failed) == (
            3,
            1,
            1,
            1,
        )

        retried = repository.claim_items(job_id=job_id, limit=1, retry_failed=True)
        assert retried == (claimed[2],)
        repository.complete_item(job_id=job_id, item=retried[0], records_accepted=50)
        repository.refresh_job_status(job_id)
        assert repository.get_job(job_id).status == "completed"
    finally:
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM krx_backfill_jobs WHERE krx_backfill_job_id = %s", (job_id,)
            )

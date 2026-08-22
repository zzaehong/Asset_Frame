import os
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import psycopg
import pytest

from asset_frame.domain.models import AssetType
from asset_frame.sources.registry import load_source_registry
from asset_frame.storage.batch import MarketDataJobItem, PostgresBatchRepository
from asset_frame.storage.postgres import PostgresIngestionRepository


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL is not configured")
def test_postgres_batch_job_can_resume_failed_items() -> None:
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
    repository = PostgresBatchRepository(connection_factory)
    job_id = repository.prepare_job(
        source_id=source.id,
        job_type="liquidity_discovery",
        country_code="US",
        as_of_date=date(2026, 8, 21),
        start_date=date(2026, 5, 23),
        end_date=date(2026, 8, 21),
        items=(
            MarketDataJobItem("AAPL", AssetType.EQUITY, "NASDAQ"),
            MarketDataJobItem("SPY", AssetType.ETF, "NYSE ARCA"),
        ),
    )
    try:
        first = repository.claim_items(job_id=job_id, limit=1, retry_failed=False)
        assert len(first) == 1
        repository.complete_item(job_id=job_id, ticker=first[0].ticker, records_accepted=60)
        second = repository.claim_items(job_id=job_id, limit=1, retry_failed=False)
        repository.fail_item(job_id=job_id, ticker=second[0].ticker, error_message="rate limited")
        repository.refresh_job_status(job_id)
        assert repository.get_job(job_id).status == "completed_with_errors"
        progress = repository.job_progress(job_id)
        assert (progress.total, progress.succeeded, progress.failed) == (2, 1, 1)

        retried = repository.claim_items(job_id=job_id, limit=1, retry_failed=True)
        assert [item.ticker for item in retried] == [second[0].ticker]
        repository.complete_item(job_id=job_id, ticker=retried[0].ticker, records_accepted=59)
        repository.refresh_job_status(job_id)
        assert repository.get_job(job_id).status == "completed"
    finally:
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM market_data_jobs WHERE market_data_job_id = %s", (job_id,))

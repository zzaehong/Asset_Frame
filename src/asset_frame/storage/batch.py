from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from asset_frame.domain.models import AssetType
from asset_frame.storage.postgres import ConnectionFactory


@dataclass(frozen=True, slots=True)
class MarketDataJobItem:
    ticker: str
    asset_type: AssetType
    exchange_code: str | None = None


@dataclass(frozen=True, slots=True)
class MarketDataJob:
    id: UUID
    source_id: str
    job_type: str
    country_code: str
    as_of_date: date
    start_date: date
    end_date: date
    status: str


@dataclass(frozen=True, slots=True)
class MarketDataJobProgress:
    job: MarketDataJob
    total: int
    pending: int
    running: int
    succeeded: int
    failed: int


class PostgresBatchRepository:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    def prepare_job(
        self,
        *,
        source_id: str,
        job_type: str,
        country_code: str,
        as_of_date: date,
        start_date: date,
        end_date: date,
        items: tuple[MarketDataJobItem, ...],
    ) -> UUID:
        if start_date > end_date:
            raise ValueError("market data job start date must not exceed end date")
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO market_data_jobs (
                    source_id, job_type, country_code, as_of_date, start_date, end_date
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (
                    source_id, job_type, country_code, as_of_date, start_date, end_date
                ) DO UPDATE SET updated_at = now()
                RETURNING market_data_job_id
                """,
                (source_id, job_type, country_code, as_of_date, start_date, end_date),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("failed to prepare market data job")
            job_id = row[0]
            cursor.executemany(
                """
                INSERT INTO market_data_job_items (
                    market_data_job_id, ticker, asset_type, exchange_code
                ) VALUES (%s, %s, %s, %s)
                ON CONFLICT (market_data_job_id, ticker) DO UPDATE SET
                    asset_type = EXCLUDED.asset_type,
                    exchange_code = EXCLUDED.exchange_code,
                    updated_at = now()
                """,
                [
                    (job_id, item.ticker, item.asset_type.value, item.exchange_code)
                    for item in items
                ],
            )
            cursor.execute(
                """
                UPDATE market_data_jobs
                SET total_items = (
                    SELECT count(*) FROM market_data_job_items
                    WHERE market_data_job_id = %s
                ), updated_at = now()
                WHERE market_data_job_id = %s
                """,
                (job_id, job_id),
            )
            return job_id

    def get_job(self, job_id: UUID) -> MarketDataJob:
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT market_data_job_id, source_id, job_type, country_code,
                       as_of_date, start_date, end_date, status
                FROM market_data_jobs WHERE market_data_job_id = %s
                """,
                (job_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise ValueError("market data job was not found")
            return MarketDataJob(*row)

    def job_progress(self, job_id: UUID) -> MarketDataJobProgress:
        job = self.get_job(job_id)
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*)::integer,
                       count(*) FILTER (WHERE status = 'pending')::integer,
                       count(*) FILTER (WHERE status = 'running')::integer,
                       count(*) FILTER (WHERE status = 'succeeded')::integer,
                       count(*) FILTER (WHERE status = 'failed')::integer
                FROM market_data_job_items WHERE market_data_job_id = %s
                """,
                (job_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("failed to read market data job progress")
            return MarketDataJobProgress(job, *row)

    def claim_items(
        self,
        *,
        job_id: UUID,
        limit: int,
        retry_failed: bool,
        stale_after: timedelta = timedelta(minutes=30),
    ) -> tuple[MarketDataJobItem, ...]:
        if limit <= 0:
            raise ValueError("claim limit must be positive")
        statuses = ["pending", "failed"] if retry_failed else ["pending"]
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE market_data_job_items
                SET status = 'pending', updated_at = now(),
                    last_error = 'requeued after stale running lease'
                WHERE market_data_job_id = %s AND status = 'running'
                  AND updated_at < now() - %s
                """,
                (job_id, stale_after),
            )
            cursor.execute(
                """
                WITH claimed AS (
                    SELECT market_data_job_id, ticker
                    FROM market_data_job_items
                    WHERE market_data_job_id = %s AND status = ANY(%s)
                    ORDER BY ticker
                    FOR UPDATE SKIP LOCKED
                    LIMIT %s
                )
                UPDATE market_data_job_items AS item
                SET status = 'running', attempts = attempts + 1,
                    last_error = NULL, updated_at = now()
                FROM claimed
                WHERE item.market_data_job_id = claimed.market_data_job_id
                  AND item.ticker = claimed.ticker
                RETURNING item.ticker, item.asset_type, item.exchange_code
                """,
                (job_id, statuses, limit),
            )
            rows = cursor.fetchall()
            cursor.execute(
                "UPDATE market_data_jobs SET status = 'running', updated_at = now() "
                "WHERE market_data_job_id = %s AND status = 'pending'",
                (job_id,),
            )
            return tuple(MarketDataJobItem(row[0], AssetType(row[1]), row[2]) for row in rows)

    def complete_item(self, *, job_id: UUID, ticker: str, records_accepted: int) -> None:
        self._finish_item(
            job_id=job_id,
            ticker=ticker,
            status="succeeded",
            records_accepted=records_accepted,
            error_message=None,
        )

    def fail_item(self, *, job_id: UUID, ticker: str, error_message: str) -> None:
        self._finish_item(
            job_id=job_id,
            ticker=ticker,
            status="failed",
            records_accepted=0,
            error_message=error_message[:1000],
        )

    def _finish_item(
        self,
        *,
        job_id: UUID,
        ticker: str,
        status: str,
        records_accepted: int,
        error_message: str | None,
    ) -> None:
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE market_data_job_items
                SET status = %s, records_accepted = %s, last_error = %s, updated_at = now()
                WHERE market_data_job_id = %s AND ticker = %s AND status = 'running'
                """,
                (status, records_accepted, error_message, job_id, ticker),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("market data job item is not running")

    def refresh_job_status(self, job_id: UUID) -> None:
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                WITH counts AS (
                    SELECT count(*) FILTER (WHERE status = 'succeeded')::integer AS succeeded,
                           count(*) FILTER (WHERE status = 'failed')::integer AS failed,
                           count(*) FILTER (WHERE status IN ('pending', 'running'))::integer
                               AS remaining
                    FROM market_data_job_items WHERE market_data_job_id = %s
                )
                UPDATE market_data_jobs AS job
                SET succeeded_items = counts.succeeded,
                    failed_items = counts.failed,
                    status = CASE
                        WHEN counts.remaining > 0 THEN 'running'
                        WHEN counts.failed > 0 THEN 'completed_with_errors'
                        ELSE 'completed'
                    END,
                    updated_at = now()
                FROM counts WHERE job.market_data_job_id = %s
                """,
                (job_id, job_id),
            )

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from asset_frame.connectors.krx import KrxDataset
from asset_frame.storage.postgres import ConnectionFactory


@dataclass(frozen=True, slots=True)
class KrxBackfillItem:
    business_date: date
    dataset: KrxDataset


@dataclass(frozen=True, slots=True)
class KrxBackfillJob:
    id: UUID
    source_id: str
    as_of_date: date
    start_date: date
    end_date: date
    status: str


@dataclass(frozen=True, slots=True)
class KrxBackfillProgress:
    job: KrxBackfillJob
    total: int
    pending: int
    running: int
    succeeded: int
    no_data: int
    failed: int


class PostgresKrxBatchRepository:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    def prepare_job(
        self,
        *,
        source_id: str,
        as_of_date: date,
        start_date: date,
        end_date: date,
        items: tuple[KrxBackfillItem, ...],
    ) -> UUID:
        if start_date > end_date:
            raise ValueError("KRX backfill start date must not exceed end date")
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO krx_backfill_jobs (source_id, as_of_date, start_date, end_date)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (source_id, as_of_date, start_date, end_date)
                DO UPDATE SET updated_at = now()
                RETURNING krx_backfill_job_id
                """,
                (source_id, as_of_date, start_date, end_date),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("failed to prepare KRX backfill job")
            job_id = row[0]
            cursor.executemany(
                """
                INSERT INTO krx_backfill_items (
                    krx_backfill_job_id, business_date, dataset
                ) VALUES (%s, %s, %s)
                ON CONFLICT (krx_backfill_job_id, business_date, dataset) DO NOTHING
                """,
                [(job_id, item.business_date, item.dataset.name.lower()) for item in items],
            )
            cursor.execute(
                """
                UPDATE krx_backfill_jobs SET total_items = (
                    SELECT count(*) FROM krx_backfill_items
                    WHERE krx_backfill_job_id = %s
                ), updated_at = now()
                WHERE krx_backfill_job_id = %s
                """,
                (job_id, job_id),
            )
            return job_id

    def get_job(self, job_id: UUID) -> KrxBackfillJob:
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT krx_backfill_job_id, source_id, as_of_date, start_date, end_date, status
                FROM krx_backfill_jobs WHERE krx_backfill_job_id = %s
                """,
                (job_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise ValueError("KRX backfill job was not found")
            return KrxBackfillJob(*row)

    def job_progress(self, job_id: UUID) -> KrxBackfillProgress:
        job = self.get_job(job_id)
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*)::integer,
                       count(*) FILTER (WHERE status = 'pending')::integer,
                       count(*) FILTER (WHERE status = 'running')::integer,
                       count(*) FILTER (WHERE status = 'succeeded')::integer,
                       count(*) FILTER (WHERE status = 'no_data')::integer,
                       count(*) FILTER (WHERE status = 'failed')::integer
                FROM krx_backfill_items WHERE krx_backfill_job_id = %s
                """,
                (job_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("failed to read KRX backfill progress")
            return KrxBackfillProgress(job, *row)

    def claim_items(
        self,
        *,
        job_id: UUID,
        limit: int,
        retry_failed: bool,
        stale_after: timedelta = timedelta(minutes=30),
    ) -> tuple[KrxBackfillItem, ...]:
        if limit <= 0:
            raise ValueError("claim limit must be positive")
        statuses = ["pending", "failed"] if retry_failed else ["pending"]
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE krx_backfill_items
                SET status = 'pending', updated_at = now(),
                    last_error = 'requeued after stale running lease'
                WHERE krx_backfill_job_id = %s AND status = 'running'
                  AND updated_at < now() - %s
                """,
                (job_id, stale_after),
            )
            cursor.execute(
                """
                WITH claimed AS (
                    SELECT krx_backfill_job_id, business_date, dataset
                    FROM krx_backfill_items
                    WHERE krx_backfill_job_id = %s AND status = ANY(%s)
                    ORDER BY business_date, dataset
                    FOR UPDATE SKIP LOCKED LIMIT %s
                )
                UPDATE krx_backfill_items AS item
                SET status = 'running', attempts = attempts + 1,
                    last_error = NULL, updated_at = now()
                FROM claimed
                WHERE item.krx_backfill_job_id = claimed.krx_backfill_job_id
                  AND item.business_date = claimed.business_date
                  AND item.dataset = claimed.dataset
                RETURNING item.business_date, item.dataset
                """,
                (job_id, statuses, limit),
            )
            rows = cursor.fetchall()
            cursor.execute(
                "UPDATE krx_backfill_jobs SET status = 'running', updated_at = now() "
                "WHERE krx_backfill_job_id = %s AND status = 'pending'",
                (job_id,),
            )
            return tuple(KrxBackfillItem(row[0], KrxDataset[row[1].upper()]) for row in rows)

    def complete_item(self, *, job_id: UUID, item: KrxBackfillItem, records_accepted: int) -> None:
        status = "succeeded" if records_accepted else "no_data"
        self._finish_item(job_id, item, status, records_accepted, None)

    def fail_item(self, *, job_id: UUID, item: KrxBackfillItem, error_message: str) -> None:
        self._finish_item(job_id, item, "failed", 0, error_message[:1000])

    def _finish_item(
        self,
        job_id: UUID,
        item: KrxBackfillItem,
        status: str,
        records_accepted: int,
        error_message: str | None,
    ) -> None:
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE krx_backfill_items
                SET status = %s, records_accepted = %s, last_error = %s, updated_at = now()
                WHERE krx_backfill_job_id = %s AND business_date = %s
                  AND dataset = %s AND status = 'running'
                """,
                (
                    status,
                    records_accepted,
                    error_message,
                    job_id,
                    item.business_date,
                    item.dataset.name.lower(),
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("KRX backfill item is not running")

    def refresh_job_status(self, job_id: UUID) -> None:
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                WITH counts AS (
                    SELECT count(*) FILTER (WHERE status = 'succeeded')::integer AS succeeded,
                           count(*) FILTER (WHERE status = 'no_data')::integer AS no_data,
                           count(*) FILTER (WHERE status = 'failed')::integer AS failed,
                           count(*) FILTER (WHERE status IN ('pending', 'running'))::integer
                               AS remaining
                    FROM krx_backfill_items WHERE krx_backfill_job_id = %s
                )
                UPDATE krx_backfill_jobs AS job
                SET succeeded_items = counts.succeeded, no_data_items = counts.no_data,
                    failed_items = counts.failed,
                    status = CASE
                        WHEN counts.remaining > 0 THEN 'running'
                        WHEN counts.failed > 0 THEN 'completed_with_errors'
                        ELSE 'completed'
                    END,
                    updated_at = now()
                FROM counts WHERE job.krx_backfill_job_id = %s
                """,
                (job_id, job_id),
            )

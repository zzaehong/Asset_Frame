from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from asset_frame.storage.postgres import ConnectionFactory


@dataclass(frozen=True, slots=True)
class UniverseCollectionItem:
    asset_id: UUID
    ticker: str
    external_identifier: str | None = None
    search_query: str | None = None


@dataclass(frozen=True, slots=True)
class UniverseCollectionJob:
    id: UUID
    source_id: str
    job_type: str
    country_code: str
    as_of_date: date
    start_date: date
    end_date: date
    max_news_records: int
    status: str


@dataclass(frozen=True, slots=True)
class UniverseCollectionProgress:
    job: UniverseCollectionJob
    total: int
    pending: int
    running: int
    succeeded: int
    no_data: int
    failed: int


class PostgresUniverseCollectionRepository:
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
        max_news_records: int,
        items: tuple[UniverseCollectionItem, ...],
    ) -> UUID:
        if start_date > end_date:
            raise ValueError("universe collection start date must not exceed end date")
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO universe_collection_jobs (
                    source_id, job_type, country_code, as_of_date, start_date, end_date,
                    max_news_records
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (
                    source_id, job_type, country_code, as_of_date, start_date, end_date,
                    max_news_records
                ) DO UPDATE SET updated_at = now()
                RETURNING universe_collection_job_id
                """,
                (
                    source_id,
                    job_type,
                    country_code,
                    as_of_date,
                    start_date,
                    end_date,
                    max_news_records,
                ),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("failed to prepare universe collection job")
            job_id = row[0]
            cursor.executemany(
                """
                INSERT INTO universe_collection_items (
                    universe_collection_job_id, asset_id, ticker,
                    external_identifier, search_query
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (universe_collection_job_id, asset_id) DO UPDATE SET
                    ticker = EXCLUDED.ticker,
                    external_identifier = EXCLUDED.external_identifier,
                    search_query = EXCLUDED.search_query,
                    updated_at = now()
                """,
                [
                    (
                        job_id,
                        item.asset_id,
                        item.ticker,
                        item.external_identifier,
                        item.search_query,
                    )
                    for item in items
                ],
            )
            cursor.execute(
                """
                UPDATE universe_collection_jobs SET total_items = (
                    SELECT count(*) FROM universe_collection_items
                    WHERE universe_collection_job_id = %s
                ), updated_at = now()
                WHERE universe_collection_job_id = %s
                """,
                (job_id, job_id),
            )
            return job_id

    def get_job(self, job_id: UUID) -> UniverseCollectionJob:
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT universe_collection_job_id, source_id, job_type, country_code,
                       as_of_date, start_date, end_date, max_news_records, status
                FROM universe_collection_jobs WHERE universe_collection_job_id = %s
                """,
                (job_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise ValueError("universe collection job was not found")
            return UniverseCollectionJob(*row)

    def job_progress(self, job_id: UUID) -> UniverseCollectionProgress:
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
                FROM universe_collection_items WHERE universe_collection_job_id = %s
                """,
                (job_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("failed to read universe collection progress")
            return UniverseCollectionProgress(job, *row)

    def claim_items(
        self,
        *,
        job_id: UUID,
        limit: int,
        retry_failed: bool,
        stale_after: timedelta = timedelta(minutes=30),
    ) -> tuple[UniverseCollectionItem, ...]:
        if limit <= 0:
            raise ValueError("claim limit must be positive")
        statuses = ["pending", "failed"] if retry_failed else ["pending"]
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE universe_collection_items
                SET status = 'pending', updated_at = now(),
                    last_error = 'requeued after stale running lease'
                WHERE universe_collection_job_id = %s AND status = 'running'
                  AND updated_at < now() - %s
                """,
                (job_id, stale_after),
            )
            cursor.execute(
                """
                WITH claimed AS (
                    SELECT universe_collection_job_id, asset_id
                    FROM universe_collection_items
                    WHERE universe_collection_job_id = %s AND status = ANY(%s)
                    ORDER BY ticker, asset_id
                    FOR UPDATE SKIP LOCKED LIMIT %s
                )
                UPDATE universe_collection_items AS item
                SET status = 'running', attempts = attempts + 1,
                    last_error = NULL, updated_at = now()
                FROM claimed
                WHERE item.universe_collection_job_id = claimed.universe_collection_job_id
                  AND item.asset_id = claimed.asset_id
                RETURNING item.asset_id, item.ticker,
                          item.external_identifier, item.search_query
                """,
                (job_id, statuses, limit),
            )
            rows = cursor.fetchall()
            cursor.execute(
                "UPDATE universe_collection_jobs SET status = 'running', updated_at = now() "
                "WHERE universe_collection_job_id = %s AND status = 'pending'",
                (job_id,),
            )
            return tuple(UniverseCollectionItem(*row) for row in rows)

    def complete_item(
        self, *, job_id: UUID, item: UniverseCollectionItem, records_accepted: int
    ) -> None:
        status = "succeeded" if records_accepted else "no_data"
        self._finish_item(job_id, item, status, records_accepted, None)

    def fail_item(self, *, job_id: UUID, item: UniverseCollectionItem, error_message: str) -> None:
        self._finish_item(job_id, item, "failed", 0, error_message[:1000])

    def _finish_item(
        self,
        job_id: UUID,
        item: UniverseCollectionItem,
        status: str,
        records_accepted: int,
        error_message: str | None,
    ) -> None:
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE universe_collection_items
                SET status = %s, records_accepted = %s, last_error = %s, updated_at = now()
                WHERE universe_collection_job_id = %s AND asset_id = %s AND status = 'running'
                """,
                (status, records_accepted, error_message, job_id, item.asset_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("universe collection item is not running")

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
                    FROM universe_collection_items WHERE universe_collection_job_id = %s
                )
                UPDATE universe_collection_jobs AS job
                SET succeeded_items = counts.succeeded, no_data_items = counts.no_data,
                    failed_items = counts.failed,
                    status = CASE
                        WHEN counts.remaining > 0 THEN 'running'
                        WHEN counts.failed > 0 THEN 'completed_with_errors'
                        ELSE 'completed'
                    END,
                    updated_at = now()
                FROM counts WHERE job.universe_collection_job_id = %s
                """,
                (job_id, job_id),
            )

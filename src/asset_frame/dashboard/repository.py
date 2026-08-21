from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

import psycopg
from psycopg import Connection


class DashboardUnavailable(RuntimeError):
    pass


class DashboardRepository(Protocol):
    def health(self) -> dict[str, object]: ...

    def overview(self) -> dict[str, object]: ...

    def recent_runs(self, *, limit: int) -> list[dict[str, object]]: ...

    def recent_snapshots(self, *, limit: int) -> list[dict[str, object]]: ...

    def assets(
        self,
        *,
        query: str | None,
        country_code: str | None,
        asset_type: str | None,
        limit: int,
        offset: int,
    ) -> dict[str, object]: ...

    def asset_detail(self, *, asset_id: UUID) -> dict[str, object] | None: ...

    def asset_prices(self, *, asset_id: UUID, limit: int, offset: int) -> dict[str, object]: ...

    def asset_filings(self, *, asset_id: UUID, limit: int, offset: int) -> dict[str, object]: ...


class PostgresDashboardRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    @contextmanager
    def _connection(self):  # type: ignore[no-untyped-def]
        try:
            with psycopg.connect(self._database_url) as connection:
                connection.execute("SET TRANSACTION READ ONLY")
                yield connection
        except psycopg.Error as error:
            raise DashboardUnavailable("PostgreSQL dashboard query failed") from error

    def health(self) -> dict[str, object]:
        with self._connection() as connection:
            database, user = connection.execute(
                "SELECT current_database(), current_user"
            ).fetchone()
        return {"status": "ok", "database": database, "user": user}

    def overview(self) -> dict[str, object]:
        with self._connection() as connection:
            totals = self._fetch_one(
                connection,
                """
                SELECT
                    (SELECT count(*) FROM sources WHERE enabled) AS enabled_sources,
                    (SELECT count(*) FROM assets) AS assets,
                    (SELECT count(*) FROM price_observations WHERE valid_to IS NULL) AS prices,
                    (SELECT count(*) FROM filing_documents) AS filings,
                    (SELECT count(*) FROM raw_snapshots) AS raw_snapshots,
                    (SELECT count(*) FROM quality_issues
                     WHERE status = 'quarantined') AS quarantined_issues,
                    (SELECT count(*) FROM ingestion_runs
                     WHERE status = 'failed') AS failed_runs,
                    (SELECT max(fetched_at) FROM raw_snapshots) AS latest_fetch_at
                """,
            )
            sources = self._fetch_all(
                connection,
                """
                SELECT
                    s.source_id,
                    s.authority,
                    s.source_role,
                    s.data_kinds,
                    s.enabled,
                    s.implementation_status,
                    latest.data_kind AS latest_data_kind,
                    latest.status AS latest_status,
                    latest.finished_at AS latest_finished_at,
                    latest.records_received,
                    latest.records_accepted,
                    latest.records_quarantined
                FROM sources AS s
                LEFT JOIN LATERAL (
                    SELECT data_kind, status, finished_at, records_received,
                           records_accepted, records_quarantined
                    FROM ingestion_runs
                    WHERE source_id = s.source_id
                    ORDER BY started_at DESC
                    LIMIT 1
                ) AS latest ON true
                ORDER BY s.enabled DESC, s.source_id
                """,
            )
        return {
            "generated_at": datetime.now(UTC),
            "totals": totals,
            "sources": sources,
        }

    def recent_runs(self, *, limit: int) -> list[dict[str, object]]:
        with self._connection() as connection:
            return self._fetch_all(
                connection,
                """
                SELECT ingestion_run_id, source_id, data_kind, status, started_at,
                       finished_at, records_received, records_accepted,
                       records_quarantined, error_code, error_message
                FROM ingestion_runs
                ORDER BY started_at DESC
                LIMIT %s
                """,
                (limit,),
            )

    def recent_snapshots(self, *, limit: int) -> list[dict[str, object]]:
        with self._connection() as connection:
            return self._fetch_all(
                connection,
                """
                SELECT raw_snapshot_id, ingestion_run_id, source_id, fetched_at,
                       http_status, content_type, content_length, sha256,
                       storage_path, request_url
                FROM raw_snapshots
                ORDER BY fetched_at DESC
                LIMIT %s
                """,
                (limit,),
            )

    def assets(
        self,
        *,
        query: str | None,
        country_code: str | None,
        asset_type: str | None,
        limit: int,
        offset: int,
    ) -> dict[str, object]:
        normalized_query = query.strip() if query else None
        search_pattern = f"%{normalized_query}%" if normalized_query else None
        filters = """
            WHERE (%s::text IS NULL OR a.country_code = %s)
              AND (%s::text IS NULL OR a.asset_type::text = %s)
              AND (
                    %s::text IS NULL
                    OR a.name ILIKE %s
                    OR EXISTS (
                        SELECT 1
                        FROM asset_identifiers AS search_identifier
                        WHERE search_identifier.asset_id = a.asset_id
                          AND search_identifier.valid_to IS NULL
                          AND search_identifier.identifier_value ILIKE %s
                    )
              )
        """
        filter_parameters = (
            country_code,
            country_code,
            asset_type,
            asset_type,
            normalized_query,
            search_pattern,
            search_pattern,
        )
        with self._connection() as connection:
            total = connection.execute(
                f"SELECT count(*) FROM assets AS a {filters}",  # noqa: S608
                filter_parameters,
            ).fetchone()[0]
            items = self._fetch_all(
                connection,
                f"""
                SELECT
                    a.asset_id,
                    a.name,
                    a.country_code,
                    a.currency,
                    a.asset_type,
                    identifiers.ticker,
                    identifiers.isin,
                    identifiers.cik,
                    identifiers.dart_corp_code,
                    identifiers.exchange_code,
                    prices.price_records,
                    prices.earliest_price_date,
                    prices.latest_price_date,
                    filings.filing_records,
                    filings.earliest_filing_date,
                    filings.latest_filing_date
                FROM assets AS a
                LEFT JOIN LATERAL (
                    SELECT
                        max(identifier_value) FILTER (
                            WHERE identifier_type = 'ticker'
                        ) AS ticker,
                        max(identifier_value) FILTER (
                            WHERE identifier_type = 'isin'
                        ) AS isin,
                        max(identifier_value) FILTER (
                            WHERE identifier_type = 'cik'
                        ) AS cik,
                        max(identifier_value) FILTER (
                            WHERE identifier_type = 'dart_corp_code'
                        ) AS dart_corp_code,
                        max(identifier_value) FILTER (
                            WHERE identifier_type = 'exchange_code'
                        ) AS exchange_code
                    FROM asset_identifiers
                    WHERE asset_id = a.asset_id AND valid_to IS NULL
                ) AS identifiers ON true
                LEFT JOIN LATERAL (
                    SELECT count(*) AS price_records,
                           min(trading_date) AS earliest_price_date,
                           max(trading_date) AS latest_price_date
                    FROM price_observations
                    WHERE asset_id = a.asset_id AND valid_to IS NULL
                ) AS prices ON true
                LEFT JOIN LATERAL (
                    SELECT count(*) AS filing_records,
                           min(filed_at) AS earliest_filing_date,
                           max(filed_at) AS latest_filing_date
                    FROM filing_documents
                    WHERE asset_id = a.asset_id
                ) AS filings ON true
                {filters}
                ORDER BY a.country_code, identifiers.ticker NULLS LAST, a.name
                LIMIT %s OFFSET %s
                """,  # noqa: S608
                (*filter_parameters, limit, offset),
            )
        return {"total": total, "limit": limit, "offset": offset, "items": items}

    def asset_detail(self, *, asset_id: UUID) -> dict[str, object] | None:
        with self._connection() as connection:
            item = self._fetch_one(
                connection,
                """
                SELECT
                    a.asset_id,
                    a.name,
                    a.country_code,
                    a.currency,
                    a.asset_type,
                    identifiers.ticker,
                    identifiers.isin,
                    identifiers.cik,
                    identifiers.dart_corp_code,
                    identifiers.exchange_code,
                    prices.price_records,
                    prices.earliest_price_date,
                    prices.latest_price_date,
                    prices.price_sources,
                    filings.filing_records,
                    filings.earliest_filing_date,
                    filings.latest_filing_date,
                    filings.filing_sources
                FROM assets AS a
                LEFT JOIN LATERAL (
                    SELECT
                        max(identifier_value) FILTER (
                            WHERE identifier_type = 'ticker'
                        ) AS ticker,
                        max(identifier_value) FILTER (
                            WHERE identifier_type = 'isin'
                        ) AS isin,
                        max(identifier_value) FILTER (
                            WHERE identifier_type = 'cik'
                        ) AS cik,
                        max(identifier_value) FILTER (
                            WHERE identifier_type = 'dart_corp_code'
                        ) AS dart_corp_code,
                        max(identifier_value) FILTER (
                            WHERE identifier_type = 'exchange_code'
                        ) AS exchange_code
                    FROM asset_identifiers
                    WHERE asset_id = a.asset_id AND valid_to IS NULL
                ) AS identifiers ON true
                LEFT JOIN LATERAL (
                    SELECT
                        count(*) AS price_records,
                        min(trading_date) AS earliest_price_date,
                        max(trading_date) AS latest_price_date,
                        array_agg(DISTINCT source_id ORDER BY source_id) AS price_sources
                    FROM price_observations
                    WHERE asset_id = a.asset_id AND valid_to IS NULL
                ) AS prices ON true
                LEFT JOIN LATERAL (
                    SELECT
                        count(*) AS filing_records,
                        min(filed_at) AS earliest_filing_date,
                        max(filed_at) AS latest_filing_date,
                        array_agg(DISTINCT source_id ORDER BY source_id) AS filing_sources
                    FROM filing_documents
                    WHERE asset_id = a.asset_id
                ) AS filings ON true
                WHERE a.asset_id = %s
                """,
                (asset_id,),
            )
        return item or None

    def asset_prices(self, *, asset_id: UUID, limit: int, offset: int) -> dict[str, object]:
        with self._connection() as connection:
            total = connection.execute(
                """
                SELECT count(*)
                FROM price_observations
                WHERE asset_id = %s AND valid_to IS NULL
                """,
                (asset_id,),
            ).fetchone()[0]
            items = self._fetch_all(
                connection,
                """
                SELECT source_id, raw_snapshot_id, trading_date, currency,
                       open, high, low, close, adjusted_close, volume,
                       price_basis, quality_status, fetched_at
                FROM price_observations
                WHERE asset_id = %s AND valid_to IS NULL
                ORDER BY trading_date DESC, source_id, price_basis
                LIMIT %s OFFSET %s
                """,
                (asset_id, limit, offset),
            )
        return {"total": total, "limit": limit, "offset": offset, "items": items}

    def asset_filings(self, *, asset_id: UUID, limit: int, offset: int) -> dict[str, object]:
        with self._connection() as connection:
            total = connection.execute(
                "SELECT count(*) FROM filing_documents WHERE asset_id = %s",
                (asset_id,),
            ).fetchone()[0]
            items = self._fetch_all(
                connection,
                """
                SELECT source_id, raw_snapshot_id, accession_number, form_type,
                       filed_at, report_period, primary_document, document_url,
                       metadata
                FROM filing_documents
                WHERE asset_id = %s
                ORDER BY filed_at DESC, accession_number DESC
                LIMIT %s OFFSET %s
                """,
                (asset_id, limit, offset),
            )
        return {"total": total, "limit": limit, "offset": offset, "items": items}

    @staticmethod
    def _fetch_one(
        connection: Connection[tuple[object, ...]],
        query: str,
        parameters: tuple[object, ...] = (),
    ) -> dict[str, object]:
        cursor = connection.execute(query, parameters)
        row = cursor.fetchone()
        if row is None:
            return {}
        return dict(zip((column.name for column in cursor.description), row, strict=True))

    @staticmethod
    def _fetch_all(
        connection: Connection[tuple[object, ...]],
        query: str,
        parameters: tuple[object, ...] = (),
    ) -> list[dict[str, object]]:
        cursor = connection.execute(query, parameters)
        columns = tuple(column.name for column in cursor.description)
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]

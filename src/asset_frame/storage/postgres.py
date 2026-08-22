from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime
from hashlib import sha256
from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Jsonb

from asset_frame.domain.models import (
    Asset,
    AssetIdentifier,
    AssetType,
    CorporateAction,
    FilingDocument,
    FinancialFact,
    IdentifierType,
    NewsArticleMention,
    PriceObservation,
    QuarantinedPrice,
    RawSnapshot,
    SourceDefinition,
)

ConnectionFactory = Callable[[], AbstractContextManager[Connection[tuple[object, ...]]]]


class PostgresIngestionRepository:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    def upsert_source(self, source: SourceDefinition) -> None:
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO sources (
                    source_id, authority, authority_type, access_method, source_role, data_kinds,
                    documentation_url, terms_url, verification_url, enabled,
                    implementation_status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_id) DO UPDATE SET
                    authority = EXCLUDED.authority,
                    authority_type = EXCLUDED.authority_type,
                    access_method = EXCLUDED.access_method,
                    source_role = EXCLUDED.source_role,
                    data_kinds = EXCLUDED.data_kinds,
                    documentation_url = EXCLUDED.documentation_url,
                    terms_url = EXCLUDED.terms_url,
                    verification_url = EXCLUDED.verification_url,
                    enabled = EXCLUDED.enabled,
                    implementation_status = EXCLUDED.implementation_status,
                    updated_at = now()
                """,
                (
                    source.id,
                    source.authority,
                    source.authority_type.value,
                    source.access_method.value,
                    source.role.value,
                    [kind.value for kind in source.data_kinds],
                    source.documentation_url,
                    source.terms_url,
                    source.verification_url,
                    source.enabled,
                    source.implementation_status.value,
                ),
            )

    def start_ingestion_run(self, *, source_id: str, data_kind: str) -> UUID:
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO ingestion_runs (source_id, data_kind)
                VALUES (%s, %s)
                RETURNING ingestion_run_id
                """,
                (source_id, data_kind),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("failed to create ingestion run")
            return row[0]

    def complete_ingestion_run(
        self,
        run_id: UUID,
        *,
        records_received: int,
        records_accepted: int,
        records_quarantined: int,
    ) -> None:
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE ingestion_runs
                SET status = 'succeeded', finished_at = now(),
                    records_received = %s, records_accepted = %s,
                    records_quarantined = %s, error_code = NULL, error_message = NULL
                WHERE ingestion_run_id = %s AND status = 'started'
                """,
                (records_received, records_accepted, records_quarantined, run_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("ingestion run is missing or already finished")

    def fail_ingestion_run(self, run_id: UUID, *, error_code: str, error_message: str) -> None:
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE ingestion_runs
                SET status = 'failed', finished_at = now(),
                    error_code = %s, error_message = %s
                WHERE ingestion_run_id = %s AND status = 'started'
                """,
                (error_code, error_message[:1000], run_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("ingestion run is missing or already finished")

    def latest_successful_run(self, *, source_id: str, data_kind: str) -> datetime | None:
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT max(finished_at)
                FROM ingestion_runs
                WHERE source_id = %s AND data_kind = %s AND status = 'succeeded'
                """,
                (source_id, data_kind),
            )
            row = cursor.fetchone()
            return row[0] if row is not None else None

    def save_raw_snapshot(self, snapshot: RawSnapshot) -> None:
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO raw_snapshots (
                    raw_snapshot_id, ingestion_run_id, source_id, request_url,
                    fetched_at, http_status,
                    content_type, content_length, sha256, storage_path
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (raw_snapshot_id) DO NOTHING
                """,
                (
                    snapshot.id,
                    snapshot.ingestion_run_id,
                    snapshot.source_id,
                    snapshot.request_url,
                    snapshot.fetched_at,
                    snapshot.http_status,
                    snapshot.content_type,
                    snapshot.content_length,
                    snapshot.sha256,
                    snapshot.storage_path,
                ),
            )

    def save_filings(self, filings: tuple[FilingDocument, ...]) -> None:
        if not filings:
            return
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO filing_documents (
                    filing_document_id, asset_id, source_id, raw_snapshot_id,
                    accession_number, form_type, report_period, filed_at, published_at,
                    primary_document, document_url, metadata
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_id, accession_number) DO NOTHING
                """,
                [
                    (
                        filing.id,
                        filing.asset_id,
                        filing.source_id,
                        filing.raw_snapshot_id,
                        filing.accession_number,
                        filing.form_type,
                        filing.report_period,
                        filing.filed_at,
                        filing.published_at,
                        filing.primary_document,
                        filing.document_url,
                        Jsonb(filing.metadata),
                    )
                    for filing in filings
                ],
            )

    def upsert_assets(
        self, assets: tuple[Asset, ...], identifiers: tuple[AssetIdentifier, ...]
    ) -> None:
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO assets (asset_id, name, asset_type, country_code, currency)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (asset_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    asset_type = EXCLUDED.asset_type,
                    country_code = EXCLUDED.country_code,
                    currency = EXCLUDED.currency
                """,
                [
                    (
                        asset.id,
                        asset.name,
                        asset.asset_type.value,
                        asset.country_code,
                        asset.currency,
                    )
                    for asset in assets
                ],
            )
            cursor.executemany(
                """
                INSERT INTO asset_identifiers (
                    asset_id, identifier_type, identifier_value, valid_from, valid_to
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (asset_id, identifier_type, identifier_value) DO NOTHING
                """,
                [
                    (
                        identifier.asset_id,
                        identifier.identifier_type.value,
                        identifier.value,
                        identifier.valid_from,
                        identifier.valid_to,
                    )
                    for identifier in identifiers
                ],
            )

    def list_assets(self, *, country_code: str) -> tuple[Asset, ...]:
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT asset_id, name, asset_type, country_code, currency
                FROM assets
                WHERE country_code = %s
                ORDER BY asset_id
                """,
                (country_code,),
            )
            return tuple(
                Asset(
                    id=row[0],
                    name=row[1],
                    asset_type=AssetType(row[2]),
                    country_code=row[3],
                    currency=row[4],
                )
                for row in cursor.fetchall()
            )

    def list_asset_identifiers(
        self, *, country_code: str, identifier_type: IdentifierType
    ) -> tuple[AssetIdentifier, ...]:
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT ai.asset_id, ai.identifier_type, ai.identifier_value,
                       ai.valid_from, ai.valid_to
                FROM asset_identifiers AS ai
                JOIN assets AS a ON a.asset_id = ai.asset_id
                WHERE a.country_code = %s
                  AND ai.identifier_type = %s
                  AND ai.valid_to IS NULL
                ORDER BY ai.asset_id, ai.identifier_value
                """,
                (country_code, identifier_type.value),
            )
            return tuple(
                AssetIdentifier(
                    asset_id=row[0],
                    identifier_type=IdentifierType(row[1]),
                    value=row[2],
                    valid_from=row[3],
                    valid_to=row[4],
                )
                for row in cursor.fetchall()
            )

    def save_asset_identifiers(self, identifiers: tuple[AssetIdentifier, ...]) -> None:
        if not identifiers:
            return
        with self._connection_factory() as connection, connection.cursor() as cursor:
            for identifier in identifiers:
                cursor.execute(
                    """
                    SELECT asset_id
                    FROM asset_identifiers
                    WHERE identifier_type = %s
                      AND identifier_value = %s
                      AND valid_to IS NULL
                      AND asset_id <> %s
                    LIMIT 1
                    """,
                    (
                        identifier.identifier_type.value,
                        identifier.value,
                        identifier.asset_id,
                    ),
                )
                if cursor.fetchone() is not None:
                    raise ValueError("regulatory identifier is already assigned to another asset")
                cursor.execute(
                    """
                    SELECT identifier_value
                    FROM asset_identifiers
                    WHERE asset_id = %s
                      AND identifier_type = %s
                      AND valid_to IS NULL
                      AND identifier_value <> %s
                    LIMIT 1
                    """,
                    (
                        identifier.asset_id,
                        identifier.identifier_type.value,
                        identifier.value,
                    ),
                )
                if cursor.fetchone() is not None:
                    raise ValueError("asset already has a different current regulatory identifier")
                cursor.execute(
                    """
                    INSERT INTO asset_identifiers (
                        asset_id, identifier_type, identifier_value, valid_from, valid_to
                    ) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (asset_id, identifier_type, identifier_value) DO NOTHING
                    """,
                    (
                        identifier.asset_id,
                        identifier.identifier_type.value,
                        identifier.value,
                        identifier.valid_from,
                        identifier.valid_to,
                    ),
                )

    def save_prices(self, prices: tuple[PriceObservation, ...]) -> None:
        if not prices:
            return
        with self._connection_factory() as connection, connection.cursor() as cursor:
            for price in prices:
                canonical_values = (
                    price.currency,
                    price.open,
                    price.high,
                    price.low,
                    price.close,
                    price.adjusted_close,
                    price.volume,
                    price.price_basis,
                    price.quality_status.value,
                )
                cursor.execute(
                    """
                    SELECT currency, open, high, low, close, adjusted_close, volume,
                           price_basis, quality_status
                    FROM price_observations
                    WHERE asset_id = %s AND source_id = %s AND trading_date = %s
                      AND valid_to IS NULL
                    ORDER BY fetched_at DESC
                    LIMIT 1
                    FOR UPDATE
                    """,
                    (price.asset_id, price.source_id, price.trading_date),
                )
                current = cursor.fetchone()
                if current == canonical_values:
                    continue
                if current is not None:
                    cursor.execute(
                        """
                        UPDATE price_observations SET valid_to = now()
                        WHERE asset_id = %s AND source_id = %s AND trading_date = %s
                          AND valid_to IS NULL
                        """,
                        (price.asset_id, price.source_id, price.trading_date),
                    )
                cursor.execute(
                    """
                    INSERT INTO price_observations (
                        asset_id, source_id, raw_snapshot_id, trading_date, currency,
                        open, high, low, close, adjusted_close, volume, price_basis,
                        fetched_at, quality_status
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        price.asset_id,
                        price.source_id,
                        price.raw_snapshot_id,
                        price.trading_date,
                        *canonical_values[:-1],
                        price.fetched_at,
                        canonical_values[-1],
                    ),
                )

    def save_corporate_actions(self, actions: tuple[CorporateAction, ...]) -> None:
        if not actions:
            return
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO corporate_actions (
                    asset_id, source_id, raw_snapshot_id, action_type, effective_at,
                    announced_at, amount, currency, ratio_numerator, ratio_denominator, metadata
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        action.asset_id,
                        action.source_id,
                        action.raw_snapshot_id,
                        action.action_type,
                        action.effective_at,
                        action.announced_at,
                        action.amount,
                        action.currency,
                        action.ratio_numerator,
                        action.ratio_denominator,
                        Jsonb(action.metadata),
                    )
                    for action in actions
                ],
            )

    def save_financial_facts(self, facts: tuple[FinancialFact, ...]) -> None:
        if not facts:
            return
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO financial_facts (
                    asset_id, source_id, raw_snapshot_id, taxonomy, concept, unit, value,
                    period_start, period_end, filed_at, published_at, revised_at,
                    accession_number, dimensions, fact_key
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_id, asset_id, fact_key)
                    WHERE fact_key IS NOT NULL DO NOTHING
                """,
                [
                    (
                        fact.asset_id,
                        fact.source_id,
                        fact.raw_snapshot_id,
                        fact.taxonomy,
                        fact.concept,
                        fact.unit,
                        fact.value,
                        fact.period_start,
                        fact.period_end,
                        fact.filed_at,
                        fact.published_at,
                        fact.revised_at,
                        fact.accession_number,
                        Jsonb(fact.dimensions),
                        _financial_fact_key(fact),
                    )
                    for fact in facts
                ],
            )

    def save_news_mentions(self, mentions: tuple[NewsArticleMention, ...]) -> None:
        if not mentions:
            return
        with self._connection_factory() as connection, connection.cursor() as cursor:
            for mention in mentions:
                cursor.execute(
                    """
                    INSERT INTO news_articles (
                        news_article_id, source_id, raw_snapshot_id, article_url, title,
                        source_domain, language, source_country, published_at, fetched_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (source_id, article_url) DO UPDATE SET
                        title = EXCLUDED.title,
                        source_domain = EXCLUDED.source_domain,
                        language = EXCLUDED.language,
                        source_country = EXCLUDED.source_country,
                        published_at = EXCLUDED.published_at,
                        fetched_at = EXCLUDED.fetched_at
                    RETURNING news_article_id
                    """,
                    (
                        mention.id,
                        mention.source_id,
                        mention.raw_snapshot_id,
                        mention.article_url,
                        mention.title,
                        mention.source_domain,
                        mention.language,
                        mention.source_country,
                        mention.published_at,
                        mention.fetched_at,
                    ),
                )
                row = cursor.fetchone()
                if row is None:
                    raise RuntimeError("failed to save news article")
                cursor.execute(
                    """
                    INSERT INTO news_asset_mentions (news_article_id, asset_id, matched_query)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (news_article_id, asset_id) DO UPDATE SET
                        matched_query = EXCLUDED.matched_query
                    """,
                    (row[0], mention.asset_id, mention.matched_query),
                )

    def save_quarantined_prices(self, prices: tuple[QuarantinedPrice, ...]) -> None:
        if not prices:
            return
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO quality_issues (
                    raw_snapshot_id, asset_id, issue_code, severity, status, details
                ) VALUES (%s, %s, %s, 'error', 'quarantined', %s)
                """,
                [
                    (
                        item.price.raw_snapshot_id,
                        item.price.asset_id,
                        item.issue_code,
                        Jsonb(item.details),
                    )
                    for item in prices
                ],
            )


def _financial_fact_key(fact: FinancialFact) -> str:
    values = (
        fact.taxonomy,
        fact.concept,
        fact.unit,
        str(fact.value),
        str(fact.period_start),
        str(fact.period_end),
        fact.filed_at.isoformat(),
        fact.accession_number or "",
        json.dumps(fact.dimensions, sort_keys=True, separators=(",", ":")),
    )
    return sha256("\x1f".join(values).encode()).hexdigest()

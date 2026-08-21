from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager

from psycopg import Connection
from psycopg.types.json import Jsonb

from asset_frame.domain.models import (
    Asset,
    AssetIdentifier,
    CorporateAction,
    FilingDocument,
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

    def save_raw_snapshot(self, snapshot: RawSnapshot) -> None:
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO raw_snapshots (
                    raw_snapshot_id, source_id, request_url, fetched_at, http_status,
                    content_type, content_length, sha256, storage_path
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (raw_snapshot_id) DO NOTHING
                """,
                (
                    snapshot.id,
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

    def save_prices(self, prices: tuple[PriceObservation, ...]) -> None:
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO price_observations (
                    asset_id, source_id, raw_snapshot_id, trading_date, currency,
                    open, high, low, close, adjusted_close, volume, price_basis,
                    fetched_at, quality_status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        price.asset_id,
                        price.source_id,
                        price.raw_snapshot_id,
                        price.trading_date,
                        price.currency,
                        price.open,
                        price.high,
                        price.low,
                        price.close,
                        price.adjusted_close,
                        price.volume,
                        price.price_basis,
                        price.fetched_at,
                        price.quality_status.value,
                    )
                    for price in prices
                ],
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

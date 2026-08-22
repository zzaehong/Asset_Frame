from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg.rows import class_row

from asset_frame.ingestion.filing_policy import FilingSelectionPolicy, filing_category
from asset_frame.ingestion.retention import RetentionPolicy, years_before


@dataclass(frozen=True, slots=True)
class RetentionResult:
    test_assets: int
    prices: int
    filings: int
    financial_facts: int
    news_mentions: int
    news_articles: int
    raw_snapshots: int
    raw_files: tuple[PrunedRawSnapshot, ...]


@dataclass(frozen=True, slots=True)
class PrunedRawSnapshot:
    snapshot_id: UUID
    storage_path: str
    delete_body: bool


@dataclass(frozen=True, slots=True)
class _FilingRow:
    filing_document_id: UUID
    asset_id: UUID
    source_id: str
    form_type: str
    filed_at: date


class PostgresRetentionService:
    def __init__(
        self,
        connection_factory: Callable[[], AbstractContextManager[psycopg.Connection]],
    ) -> None:
        self._connection_factory = connection_factory

    def enforce(
        self,
        *,
        as_of_date: date,
        policy: RetentionPolicy,
        filing_policy: FilingSelectionPolicy,
        apply: bool,
    ) -> RetentionResult:
        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                test_assets = self._remove_exchange_test_assets(cursor)
                prices = self._prune_prices(cursor, as_of_date, policy)
                filings = self._prune_filings(cursor, as_of_date, policy, filing_policy)
                financial_facts = self._prune_facts(cursor, as_of_date, policy)
                news_mentions, news_articles = self._prune_news(cursor, as_of_date, policy)
                raw_snapshots = self._prune_unreferenced_snapshots(cursor, as_of_date, policy)
            if not apply:
                connection.rollback()
            return RetentionResult(
                test_assets,
                prices,
                filings,
                financial_facts,
                news_mentions,
                news_articles,
                len(raw_snapshots),
                raw_snapshots,
            )

    @staticmethod
    def _remove_exchange_test_assets(cursor: psycopg.Cursor) -> int:
        cursor.execute(
            """
            SELECT DISTINCT a.asset_id, ai.identifier_value
            FROM assets a
            JOIN asset_identifiers ai ON ai.asset_id = a.asset_id
            WHERE ai.identifier_type = 'ticker'
              AND ai.identifier_value ~ '^[ACMNPZ]?TEST(-[A-Z])?$'
            """
        )
        rows = cursor.fetchall()
        if not rows:
            return 0
        asset_ids = [row[0] for row in rows]
        tickers = [row[1] for row in rows]
        for table in (
            "analysis_universe_memberships",
            "quality_issues",
            "news_asset_mentions",
            "corporate_actions",
            "financial_facts",
            "filing_documents",
            "price_observations",
            "asset_identifiers",
        ):
            cursor.execute(f"DELETE FROM {table} WHERE asset_id = ANY(%s)", (asset_ids,))
        cursor.execute("DELETE FROM market_data_job_items WHERE ticker = ANY(%s)", (tickers,))
        cursor.execute(
            """
            UPDATE market_data_jobs job SET total_items = counts.total_items
            FROM (
                SELECT market_data_job_id, count(*)::integer AS total_items
                FROM market_data_job_items GROUP BY market_data_job_id
            ) counts
            WHERE counts.market_data_job_id = job.market_data_job_id
            """
        )
        cursor.execute("DELETE FROM assets WHERE asset_id = ANY(%s)", (asset_ids,))
        return len(asset_ids)

    @staticmethod
    def _prune_prices(cursor: psycopg.Cursor, as_of_date: date, policy: RetentionPolicy) -> int:
        cursor.execute(
            """
            WITH ranked AS (
                SELECT ctid,
                       row_number() OVER (
                           PARTITION BY asset_id, source_id
                           ORDER BY trading_date DESC, valid_from DESC
                       ) AS position
                FROM price_observations
            )
            DELETE FROM price_observations prices USING ranked
            WHERE prices.ctid = ranked.ctid
              AND (
                  prices.trading_date < %s OR ranked.position > %s OR
                  prices.open IS NULL OR prices.high IS NULL OR prices.low IS NULL
              )
            """,
            (
                years_before(as_of_date, policy.price_lookback_years),
                policy.price_max_observations_per_asset_source,
            ),
        )
        return cursor.rowcount

    @staticmethod
    def _prune_filings(
        cursor: psycopg.Cursor,
        as_of_date: date,
        policy: RetentionPolicy,
        filing_policy: FilingSelectionPolicy,
    ) -> int:
        with cursor.connection.cursor(row_factory=class_row(_FilingRow)) as rows_cursor:
            rows_cursor.execute(
                """
                SELECT filing_document_id, asset_id, source_id, form_type, filed_at
                FROM filing_documents
                ORDER BY asset_id, source_id, filed_at DESC, filing_document_id
                """
            )
            rows: Iterator[_FilingRow] = iter(rows_cursor)
            keep: list[UUID] = []
            categories: list[tuple[str, str, UUID]] = []
            counts: defaultdict[tuple[UUID, str], int] = defaultdict(int)
            cutoff = years_before(as_of_date, policy.filing_lookback_years)
            for row in rows:
                category = filing_category(row.source_id, row.form_type, filing_policy)
                key = (row.asset_id, row.source_id)
                if (
                    category is None
                    or row.filed_at < cutoff
                    or counts[key] >= policy.filing_max_documents_per_asset_source
                ):
                    continue
                counts[key] += 1
                keep.append(row.filing_document_id)
                categories.append((filing_policy.id, category, row.filing_document_id))
        cursor.execute(
            "DELETE FROM filing_documents WHERE NOT (filing_document_id = ANY(%s))",
            (keep,),
        )
        deleted = cursor.rowcount
        cursor.executemany(
            """
            UPDATE filing_documents SET metadata = metadata ||
                jsonb_build_object(
                    'selection_policy', %s::text, 'selection_category', %s::text
                )
            WHERE filing_document_id = %s
            """,
            categories,
        )
        return deleted

    @staticmethod
    def _prune_facts(cursor: psycopg.Cursor, as_of_date: date, policy: RetentionPolicy) -> int:
        cursor.execute(
            """
            WITH ranked AS (
                SELECT financial_fact_id,
                       row_number() OVER (
                           PARTITION BY asset_id, source_id
                           ORDER BY period_end DESC, filed_at DESC, financial_fact_id
                       ) AS position
                FROM financial_facts
            )
            DELETE FROM financial_facts facts USING ranked
            WHERE facts.financial_fact_id = ranked.financial_fact_id
              AND (facts.period_end < %s OR ranked.position > %s)
            """,
            (
                years_before(as_of_date, policy.fact_lookback_years),
                policy.fact_max_per_asset_source,
            ),
        )
        return cursor.rowcount

    @staticmethod
    def _prune_news(
        cursor: psycopg.Cursor, as_of_date: date, policy: RetentionPolicy
    ) -> tuple[int, int]:
        cutoff = datetime.combine(
            as_of_date - timedelta(days=policy.news_lookback_days - 1), time.min, UTC
        )
        cursor.execute(
            """
            WITH ranked AS (
                SELECT mentions.ctid,
                       row_number() OVER (
                           PARTITION BY mentions.asset_id
                           ORDER BY articles.published_at DESC, articles.news_article_id
                       ) AS position,
                       articles.published_at
                FROM news_asset_mentions mentions
                JOIN news_articles articles USING (news_article_id)
            )
            DELETE FROM news_asset_mentions mentions USING ranked
            WHERE mentions.ctid = ranked.ctid
              AND (ranked.published_at < %s OR ranked.position > %s)
            """,
            (cutoff, policy.news_max_articles_per_asset),
        )
        deleted_mentions = cursor.rowcount
        cursor.execute(
            """
            DELETE FROM news_articles articles
            WHERE articles.published_at < %s
               OR NOT EXISTS (
                   SELECT 1 FROM news_asset_mentions mentions
                   WHERE mentions.news_article_id = articles.news_article_id
               )
            """,
            (cutoff,),
        )
        return deleted_mentions, cursor.rowcount

    @staticmethod
    def _prune_unreferenced_snapshots(
        cursor: psycopg.Cursor, as_of_date: date, policy: RetentionPolicy
    ) -> tuple[PrunedRawSnapshot, ...]:
        cutoff = datetime.combine(
            as_of_date - timedelta(days=policy.raw_unreferenced_lookback_days), time.min, UTC
        )
        cursor.execute(
            """
            DELETE FROM raw_snapshots snapshots
            WHERE snapshots.fetched_at < %s
              AND NOT EXISTS (
                  SELECT 1 FROM price_observations p
                  WHERE p.raw_snapshot_id = snapshots.raw_snapshot_id
              )
              AND NOT EXISTS (
                  SELECT 1 FROM corporate_actions c
                  WHERE c.raw_snapshot_id = snapshots.raw_snapshot_id
              )
              AND NOT EXISTS (
                  SELECT 1 FROM financial_facts f
                  WHERE f.raw_snapshot_id = snapshots.raw_snapshot_id
              )
              AND NOT EXISTS (
                  SELECT 1 FROM filing_documents d
                  WHERE d.raw_snapshot_id = snapshots.raw_snapshot_id
              )
              AND NOT EXISTS (
                  SELECT 1 FROM news_articles n
                  WHERE n.raw_snapshot_id = snapshots.raw_snapshot_id
              )
            RETURNING raw_snapshot_id, storage_path
            """,
            (cutoff,),
        )
        deleted = cursor.fetchall()
        results = []
        for snapshot_id, storage_path in deleted:
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM raw_snapshots WHERE storage_path = %s)",
                (storage_path,),
            )
            row = cursor.fetchone()
            results.append(PrunedRawSnapshot(snapshot_id, storage_path, not bool(row[0])))
        return tuple(results)


def delete_pruned_raw_files(root: Path, snapshots: tuple[PrunedRawSnapshot, ...]) -> int:
    resolved_root = root.resolve()
    deleted = 0
    for snapshot in snapshots:
        metadata = (
            resolved_root
            / Path(snapshot.storage_path).parts[0]
            / "snapshots"
            / f"{snapshot.snapshot_id}.json"
        )
        candidates = [metadata]
        if snapshot.delete_body:
            candidates.append(resolved_root / snapshot.storage_path)
        for candidate in candidates:
            resolved = candidate.resolve()
            if not resolved.is_relative_to(resolved_root):
                raise RuntimeError(f"unsafe raw retention path: {resolved}")
            if resolved.exists():
                resolved.unlink()
                deleted += 1
    return deleted

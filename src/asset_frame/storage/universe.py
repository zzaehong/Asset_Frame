from __future__ import annotations

from datetime import date
from uuid import UUID

from asset_frame.domain.models import AssetType
from asset_frame.ingestion.universe import (
    LiquidityCandidate,
    UniverseMembership,
    UniversePolicy,
    UniverseSelection,
)
from asset_frame.storage.postgres import ConnectionFactory


class PostgresUniverseRepository:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    def liquidity_candidates(
        self,
        *,
        country_code: str,
        as_of_date: date,
        lookback_observations: int,
        pinned_tickers: frozenset[str],
    ) -> tuple[LiquidityCandidate, ...]:
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                WITH current_tickers AS (
                    SELECT DISTINCT ON (ai.asset_id)
                           ai.asset_id, upper(ai.identifier_value) AS ticker
                    FROM asset_identifiers AS ai
                    WHERE ai.identifier_type = 'ticker'
                      AND ai.valid_to IS NULL
                    ORDER BY ai.asset_id, ai.identifier_value
                ), latest_prices AS (
                    SELECT DISTINCT ON (p.asset_id, p.trading_date)
                           p.asset_id, p.trading_date, p.close * p.volume AS dollar_volume
                    FROM price_observations AS p
                    JOIN assets AS a ON a.asset_id = p.asset_id
                    WHERE a.country_code = %s
                      AND p.trading_date <= %s
                      AND p.quality_status = 'accepted'
                      AND p.valid_to IS NULL
                      AND p.close >= 0
                      AND p.volume >= 0
                    ORDER BY p.asset_id, p.trading_date, p.fetched_at DESC
                ), ranked_prices AS (
                    SELECT lp.*,
                           row_number() OVER (
                               PARTITION BY lp.asset_id ORDER BY lp.trading_date DESC
                           ) AS observation_rank
                    FROM latest_prices AS lp
                ), liquidity AS (
                    SELECT asset_id,
                           percentile_cont(0.5) WITHIN GROUP (ORDER BY dollar_volume)
                               AS median_dollar_volume,
                           count(*)::integer AS observation_count
                    FROM ranked_prices
                    WHERE observation_rank <= %s
                    GROUP BY asset_id
                )
                SELECT a.asset_id, ticker.ticker, a.asset_type,
                       liquidity.median_dollar_volume, coalesce(liquidity.observation_count, 0),
                       ticker.ticker = ANY(%s)
                FROM assets AS a
                JOIN current_tickers AS ticker ON ticker.asset_id = a.asset_id
                LEFT JOIN liquidity ON liquidity.asset_id = a.asset_id
                WHERE a.country_code = %s
                ORDER BY ticker.ticker
                """,
                (
                    country_code,
                    as_of_date,
                    lookback_observations,
                    sorted(pinned_tickers),
                    country_code,
                ),
            )
            return tuple(
                LiquidityCandidate(
                    asset_id=row[0],
                    ticker=row[1],
                    asset_type=AssetType(row[2]),
                    median_dollar_volume=row[3],
                    observation_count=row[4],
                    pinned=row[5],
                )
                for row in cursor.fetchall()
            )

    def save_selection(self, selection: UniverseSelection, policy: UniversePolicy) -> UUID:
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO analysis_universe_runs (
                    country_code, as_of_date, lookback_observations, minimum_observations,
                    equity_limit, etf_limit, input_hash
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (country_code, as_of_date, input_hash) DO UPDATE SET
                    input_hash = EXCLUDED.input_hash
                RETURNING analysis_universe_run_id
                """,
                (
                    selection.country_code,
                    selection.as_of_date,
                    policy.lookback_observations,
                    policy.minimum_observations,
                    policy.equity_limit,
                    policy.etf_limit,
                    selection.input_hash,
                ),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("failed to save analysis universe run")
            run_id = row[0]
            cursor.execute(
                "DELETE FROM analysis_universe_memberships WHERE analysis_universe_run_id = %s",
                (run_id,),
            )
            cursor.executemany(
                """
                INSERT INTO analysis_universe_memberships (
                    analysis_universe_run_id, asset_id, asset_type, ticker, selected_rank,
                    median_dollar_volume, observation_count, pinned, selection_reason
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        run_id,
                        item.asset_id,
                        item.asset_type.value,
                        item.ticker,
                        item.selected_rank,
                        item.median_dollar_volume,
                        item.observation_count,
                        item.pinned,
                        item.selection_reason,
                    )
                    for item in selection.memberships
                ],
            )
            return run_id

    def latest_memberships(
        self, *, country_code: str, as_of_date: date
    ) -> tuple[UniverseMembership, ...]:
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT membership.asset_id, membership.ticker, membership.asset_type,
                       membership.selected_rank, membership.median_dollar_volume,
                       membership.observation_count, membership.pinned,
                       membership.selection_reason
                FROM analysis_universe_memberships AS membership
                JOIN analysis_universe_runs AS run
                  ON run.analysis_universe_run_id = membership.analysis_universe_run_id
                WHERE run.analysis_universe_run_id = (
                    SELECT analysis_universe_run_id
                    FROM analysis_universe_runs
                    WHERE country_code = %s AND as_of_date <= %s
                    ORDER BY as_of_date DESC, created_at DESC
                    LIMIT 1
                )
                ORDER BY membership.asset_type, membership.selected_rank
                """,
                (country_code, as_of_date),
            )
            return tuple(
                UniverseMembership(
                    asset_id=row[0],
                    ticker=row[1],
                    asset_type=AssetType(row[2]),
                    selected_rank=row[3],
                    median_dollar_volume=row[4],
                    observation_count=row[5],
                    pinned=row[6],
                    selection_reason=row[7],
                )
                for row in cursor.fetchall()
            )

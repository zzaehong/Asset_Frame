from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import psycopg

from asset_frame.storage.postgres import ConnectionFactory


@dataclass(frozen=True, slots=True)
class SymbolReservation:
    source_id: str
    usage_month: date
    symbol: str
    accepted: bool
    already_reserved: bool
    unique_symbol_count: int
    unique_symbol_limit: int


class PostgresUniverseV2Repository:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    def reserve_monthly_symbol(
        self,
        *,
        source_id: str,
        symbol: str,
        used_at: datetime,
        unique_symbol_limit: int,
    ) -> SymbolReservation:
        normalized_symbol = symbol.strip().upper()
        if not source_id.strip():
            raise ValueError("source_id is required")
        if not normalized_symbol:
            raise ValueError("symbol is required")
        if unique_symbol_limit <= 0:
            raise ValueError("unique_symbol_limit must be positive")
        usage_month = date(used_at.year, used_at.month, 1)

        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"provider-symbol-budget:{source_id}:{usage_month.isoformat()}",),
            )
            cursor.execute(
                """
                SELECT request_count
                FROM provider_monthly_symbol_usage
                WHERE source_id = %s AND usage_month = %s AND symbol = %s
                """,
                (source_id, usage_month, normalized_symbol),
            )
            existing = cursor.fetchone()
            if existing is not None:
                cursor.execute(
                    """
                    UPDATE provider_monthly_symbol_usage
                    SET last_used_at = greatest(last_used_at, %s),
                        first_used_at = least(first_used_at, %s),
                        request_count = request_count + 1
                    WHERE source_id = %s AND usage_month = %s AND symbol = %s
                    """,
                    (used_at, used_at, source_id, usage_month, normalized_symbol),
                )
                unique_count = self._monthly_unique_count(cursor, source_id, usage_month)
                return SymbolReservation(
                    source_id,
                    usage_month,
                    normalized_symbol,
                    True,
                    True,
                    unique_count,
                    unique_symbol_limit,
                )

            unique_count = self._monthly_unique_count(cursor, source_id, usage_month)
            if unique_count >= unique_symbol_limit:
                return SymbolReservation(
                    source_id,
                    usage_month,
                    normalized_symbol,
                    False,
                    False,
                    unique_count,
                    unique_symbol_limit,
                )

            cursor.execute(
                """
                INSERT INTO provider_monthly_symbol_usage (
                    source_id, usage_month, symbol, first_used_at, last_used_at
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                (source_id, usage_month, normalized_symbol, used_at, used_at),
            )
            return SymbolReservation(
                source_id,
                usage_month,
                normalized_symbol,
                True,
                False,
                unique_count + 1,
                unique_symbol_limit,
            )

    @staticmethod
    def _monthly_unique_count(
        cursor: psycopg.Cursor[tuple[object, ...]], source_id: str, usage_month: date
    ) -> int:
        cursor.execute(
            """
            SELECT count(*)
            FROM provider_monthly_symbol_usage
            WHERE source_id = %s AND usage_month = %s
            """,
            (source_id, usage_month),
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("failed to count provider monthly symbols")
        return int(row[0])

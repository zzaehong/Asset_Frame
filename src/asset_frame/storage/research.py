from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from asset_frame.returns.series import IndexPoint, MacroPoint, MonthlyReturn, PricePoint
from asset_frame.storage.sqlite import SqliteIngestionRepository
from asset_frame.universe import InceptionCheck

_SCHEMA = """
CREATE TABLE IF NOT EXISTS universe_ingest_log (
    ticker TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    PRIMARY KEY (ticker, as_of_date)
);

CREATE TABLE IF NOT EXISTS universe_verification (
    universe_verification_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    expected TEXT NOT NULL,
    provider_start TEXT,
    first_price_date TEXT,
    status TEXT NOT NULL CHECK (status IN ('ok', 'mismatch')),
    checked_at TEXT NOT NULL
);

-- Each build appends a full set sharing one computed_at; readers use the latest build.
CREATE TABLE IF NOT EXISTS monthly_return (
    ticker TEXT NOT NULL,
    month_end TEXT NOT NULL,
    total_return TEXT NOT NULL,
    is_proxy INTEGER NOT NULL CHECK (is_proxy IN (0, 1)),
    source_price_version TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    calc_version TEXT NOT NULL,
    PRIMARY KEY (ticker, month_end, computed_at)
);

-- Stand-in months for assets younger than the study period; kept apart from monthly_return so every
-- existing analysis keeps reading real ETF history only. Each build appends a full set.
CREATE TABLE IF NOT EXISTS proxy_return (
    ticker TEXT NOT NULL,
    month_end TEXT NOT NULL,
    total_return TEXT NOT NULL,
    proxy_ticker TEXT NOT NULL,
    fidelity TEXT NOT NULL,
    source_price_version TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    calc_version TEXT NOT NULL,
    PRIMARY KEY (ticker, month_end, computed_at)
);

CREATE TABLE IF NOT EXISTS proxy_check (
    ticker TEXT NOT NULL,
    proxy_ticker TEXT NOT NULL,
    fidelity TEXT NOT NULL,
    overlap_months INTEGER NOT NULL,
    correlation REAL,
    annual_tracking_difference REAL,
    mean_abs_difference REAL,
    used INTEGER NOT NULL CHECK (used IN (0, 1)),
    reason TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    calc_version TEXT NOT NULL,
    PRIMARY KEY (ticker, computed_at)
);

CREATE TABLE IF NOT EXISTS return_anomaly (
    ticker TEXT NOT NULL,
    trading_date TEXT NOT NULL,
    daily_return TEXT NOT NULL,
    source_price_version TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    calc_version TEXT NOT NULL,
    PRIMARY KEY (ticker, trading_date, computed_at)
);
"""


@dataclass(frozen=True, slots=True)
class ProxyCheckRow:
    ticker: str
    proxy_ticker: str
    fidelity: str
    overlap_months: int
    correlation: float | None
    annual_tracking_difference: float | None
    mean_abs_difference: float | None
    used: bool
    reason: str


class ResearchStore:
    """Universe bookkeeping and derived return series on the same SQLite file."""

    def __init__(self, path: Path) -> None:
        SqliteIngestionRepository(path)  # ensures the ingestion tables this store reads exist
        self._path = path
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:
                yield connection
        finally:
            connection.close()

    def is_ingest_complete(self, ticker: str, as_of: date) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM universe_ingest_log WHERE ticker = ? AND as_of_date = ?",
                (ticker, as_of.isoformat()),
            ).fetchone()
        return row is not None

    def mark_ingest_complete(self, ticker: str, as_of: date) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO universe_ingest_log VALUES (?, ?, ?)",
                (ticker, as_of.isoformat(), _now()),
            )

    def last_price_date(self, asset_id: UUID) -> date | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT MAX(trading_date) FROM price_observations WHERE asset_id = ?",
                (str(asset_id),),
            ).fetchone()
        return date.fromisoformat(row[0]) if row[0] else None

    def price_points(self, asset_id: UUID) -> tuple[PricePoint, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT trading_date, adjusted_close, raw_snapshot_id, fetched_at
                FROM price_observations
                WHERE asset_id = ? AND adjusted_close IS NOT NULL
                ORDER BY trading_date, fetched_at
                """,
                (str(asset_id),),
            ).fetchall()
        return tuple(
            PricePoint(date.fromisoformat(row[0]), Decimal(row[1]), row[2], row[3]) for row in rows
        )

    def dividend_inputs(
        self, asset_id: UUID
    ) -> tuple[
        list[tuple[date, Decimal]],
        list[tuple[date, Decimal]],
        tuple[date, Decimal] | None,
        date | None,
    ]:
        """Dividends, splits, (latest date, raw close) and first price date of one asset."""
        with self._connect() as connection:
            actions = connection.execute(
                "SELECT action_type, effective_at, amount, ratio_numerator, ratio_denominator "
                "FROM corporate_actions WHERE asset_id = ? "
                "AND action_type IN ('cash_dividend', 'split')",
                (str(asset_id),),
            ).fetchall()
            latest = connection.execute(
                "SELECT trading_date, close FROM price_observations WHERE asset_id = ? "
                "ORDER BY trading_date DESC, fetched_at DESC LIMIT 1",
                (str(asset_id),),
            ).fetchone()
            first = connection.execute(
                "SELECT MIN(trading_date) FROM price_observations WHERE asset_id = ?",
                (str(asset_id),),
            ).fetchone()
        dividends = [
            (date.fromisoformat(r[1]), Decimal(r[2])) for r in actions if r[0] == "cash_dividend"
        ]
        splits = [
            (date.fromisoformat(r[1]), Decimal(r[3]) / Decimal(r[4]))
            for r in actions
            if r[0] == "split"
        ]
        return (
            dividends,
            splits,
            None if latest is None else (date.fromisoformat(latest[0]), Decimal(latest[1])),
            None if first[0] is None else date.fromisoformat(first[0]),
        )

    def daily_bars(self, asset_id: UUID) -> list[tuple[date, float, float, float, float, float]]:
        """(date, open, high, low, raw close, volume) per trading date, latest fetch of it."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT trading_date, open, high, low, close, volume FROM price_observations "
                "WHERE asset_id = ? ORDER BY trading_date, fetched_at",
                (str(asset_id),),
            ).fetchall()
        latest = {row[0]: row for row in rows}  # later fetches overwrite earlier ones
        return [
            (date.fromisoformat(d), float(o), float(h), float(low), float(c), float(v))
            for d, o, h, low, c, v in (latest[key] for key in sorted(latest))
        ]

    def latest_raw_snapshot_path(self, *, source_id: str, request_url: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT storage_path FROM raw_snapshots
                WHERE source_id = ? AND request_url = ? AND http_status = 200
                ORDER BY fetched_at DESC LIMIT 1
                """,
                (source_id, request_url),
            ).fetchone()
        return None if row is None else row[0]

    def macro_points(self, series_id: str) -> tuple[MacroPoint, ...]:
        """Latest fetched value per observation date (current vintage, not ALFRED)."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT observation_date, value, raw_snapshot_id FROM (
                    SELECT observation_date, value, raw_snapshot_id,
                           row_number() OVER (
                               PARTITION BY observation_date
                               ORDER BY fetched_at DESC, macro_observation_id DESC
                           ) AS rank
                    FROM macro_observation WHERE series_id = ?
                ) WHERE rank = 1 ORDER BY observation_date
                """,
                (series_id,),
            ).fetchall()
        return tuple(
            MacroPoint(
                date.fromisoformat(row[0]), None if row[1] is None else Decimal(row[1]), row[2]
            )
            for row in rows
        )

    def macro_first_releases(self, series_id: str) -> tuple[tuple[date, date, Decimal | None], ...]:
        """(observation date, first-published date, first-published value), newest fetch per date.

        Only meaningful for series collected with output_type=4 (see FIRST_RELEASE_SERIES).
        """
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT observation_date, realtime_start, value FROM (
                    SELECT observation_date, realtime_start, value,
                           row_number() OVER (
                               PARTITION BY observation_date
                               ORDER BY fetched_at DESC, macro_observation_id DESC
                           ) AS rank
                    FROM macro_observation WHERE series_id = ?
                ) WHERE rank = 1 ORDER BY observation_date
                """,
                (series_id,),
            ).fetchall()
        return tuple(
            (
                date.fromisoformat(row[0]),
                date.fromisoformat(row[1]),
                None if row[2] is None else Decimal(row[2]),
            )
            for row in rows
        )

    def save_verification(self, checks: Iterable[InceptionCheck]) -> None:
        checked_at = _now()
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO universe_verification (
                    ticker, expected, provider_start, first_price_date, status, checked_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        check.ticker,
                        check.expected.isoformat(),
                        _iso(check.provider_start),
                        _iso(check.first_price_date),
                        check.status,
                        checked_at,
                    )
                    for check in checks
                ],
            )

    def save_build(
        self,
        returns: dict[str, tuple[MonthlyReturn, ...]],
        anomalies: dict[str, tuple[IndexPoint, ...]],
        *,
        calc_version: str,
    ) -> str:
        computed_at = _now()
        with self._connect() as connection:
            connection.executemany(
                "INSERT INTO monthly_return VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        ticker,
                        item.month_end.isoformat(),
                        str(item.total_return),
                        int(item.is_proxy),
                        item.source_price_version,
                        computed_at,
                        calc_version,
                    )
                    for ticker, items in returns.items()
                    for item in items
                ],
            )
            connection.executemany(
                "INSERT INTO return_anomaly VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        ticker,
                        point.trading_date.isoformat(),
                        str(point.daily_return),
                        point.snapshot_id or "",
                        computed_at,
                        calc_version,
                    )
                    for ticker, points in anomalies.items()
                    for point in points
                ],
            )
        return computed_at

    def latest_returns(self) -> dict[str, dict[date, Decimal]]:
        """Monthly total returns per ticker from the latest build."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT ticker, month_end, total_return FROM monthly_return
                WHERE computed_at = (SELECT max(computed_at) FROM monthly_return)
                ORDER BY ticker, month_end
                """
            ).fetchall()
        result: dict[str, dict[date, Decimal]] = {}
        for ticker, month_end, total_return in rows:
            result.setdefault(ticker, {})[date.fromisoformat(month_end)] = Decimal(total_return)
        return result

    def save_proxy_build(
        self,
        returns: dict[str, tuple[MonthlyReturn, ...]],
        checks: Iterable[ProxyCheckRow],
        *,
        proxy_by_target: dict[str, tuple[str, str]],
        calc_version: str,
    ) -> str:
        """Append one build: spliced months (only for used proxies) and every check outcome."""
        computed_at = _now()
        with self._connect() as connection:
            connection.executemany(
                "INSERT INTO proxy_return VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        ticker,
                        item.month_end.isoformat(),
                        str(item.total_return),
                        proxy_by_target[ticker][0],
                        proxy_by_target[ticker][1],
                        item.source_price_version,
                        computed_at,
                        calc_version,
                    )
                    for ticker, items in returns.items()
                    for item in items
                ],
            )
            connection.executemany(
                "INSERT INTO proxy_check VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        row.ticker,
                        row.proxy_ticker,
                        row.fidelity,
                        row.overlap_months,
                        row.correlation,
                        row.annual_tracking_difference,
                        row.mean_abs_difference,
                        int(row.used),
                        row.reason,
                        computed_at,
                        calc_version,
                    )
                    for row in checks
                ],
            )
        return computed_at

    def latest_proxy_returns(self) -> dict[str, dict[date, Decimal]]:
        """Stand-in monthly returns per target from the latest proxy build."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT ticker, month_end, total_return FROM proxy_return
                WHERE computed_at = (SELECT max(computed_at) FROM proxy_return)
                ORDER BY ticker, month_end
                """
            ).fetchall()
        result: dict[str, dict[date, Decimal]] = {}
        for ticker, month_end, total_return in rows:
            result.setdefault(ticker, {})[date.fromisoformat(month_end)] = Decimal(total_return)
        return result

    def latest_proxy_checks(self) -> tuple[ProxyCheckRow, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT ticker, proxy_ticker, fidelity, overlap_months, correlation,
                       annual_tracking_difference, mean_abs_difference, used, reason
                FROM proxy_check
                WHERE computed_at = (SELECT max(computed_at) FROM proxy_check)
                ORDER BY ticker
                """
            ).fetchall()
        return tuple(ProxyCheckRow(*row[:7], bool(row[7]), row[8]) for row in rows)

    def latest_build(self) -> tuple[dict[str, list[tuple[date, bool]]], dict[str, int]]:
        """Month ends (with proxy flag) and anomaly counts per ticker from the latest build."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT ticker, month_end, is_proxy FROM monthly_return
                WHERE computed_at = (SELECT max(computed_at) FROM monthly_return)
                ORDER BY ticker, month_end
                """
            ).fetchall()
            anomaly_rows = connection.execute(
                """
                SELECT ticker, count(*) FROM return_anomaly
                WHERE computed_at = (SELECT max(computed_at) FROM monthly_return)
                GROUP BY ticker
                """
            ).fetchall()
        months: dict[str, list[tuple[date, bool]]] = {}
        for ticker, month_end, is_proxy in rows:
            months.setdefault(ticker, []).append((date.fromisoformat(month_end), bool(is_proxy)))
        return months, dict(anomaly_rows)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _iso(value: date | None) -> str | None:
    return None if value is None else value.isoformat()

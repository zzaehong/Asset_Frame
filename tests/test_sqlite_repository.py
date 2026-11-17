import json
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

from test_tiingo_connector import metadata_body, prices_body

from asset_frame.domain.models import AssetType, FetchResponse, IdentifierType
from asset_frame.ingestion.tiingo_service import TiingoEodCollector
from asset_frame.sources.registry import load_source_registry
from asset_frame.storage.raw import FileRawStore
from asset_frame.storage.sqlite import SqliteIngestionRepository


class FixedTimeTransport:
    def __init__(self, responses: list[bytes], fetched_at: datetime) -> None:
        self.responses = responses
        self.fetched_at = fetched_at

    def fetch(self, request):  # type: ignore[no-untyped-def]
        return FetchResponse(
            status_code=200,
            body=self.responses.pop(0),
            headers={"Content-Type": "application/json"},
            fetched_at=self.fetched_at,
        )


def collect(db_path: Path, raw_path: Path, prices: bytes, fetched_at: datetime) -> None:
    source = next(
        source
        for source in load_source_registry(Path("config/sources.toml"))
        if source.id == "tiingo-eod"
    )
    TiingoEodCollector(
        source=source,
        transport=FixedTimeTransport([metadata_body(), prices], fetched_at),
        raw_store=FileRawStore(raw_path),
        repository=SqliteIngestionRepository(db_path),
    ).collect(
        ticker="AAPL",
        asset_type=AssetType.EQUITY,
        api_key="secret",
        start_date=date(2026, 8, 19),
        end_date=date(2026, 8, 20),
    )


def rows(db_path: Path, sql: str) -> list[tuple]:
    with sqlite3.connect(db_path) as connection:
        return connection.execute(sql).fetchall()


def test_save_and_read_back_round_trip(tmp_path: Path) -> None:
    db_path = tmp_path / "db" / "asset_frame.sqlite3"
    collect(db_path, tmp_path / "raw", prices_body(), datetime(2026, 8, 21, tzinfo=UTC))

    reopened = SqliteIngestionRepository(db_path)
    (asset,) = reopened.list_assets(country_code="US")
    assert asset.name == "Apple Inc"
    assert asset.asset_type is AssetType.EQUITY
    (ticker,) = reopened.list_asset_identifiers(
        country_code="US", identifier_type=IdentifierType.TICKER
    )
    assert (ticker.asset_id, ticker.value) == (asset.id, "AAPL")

    assert rows(
        db_path,
        "SELECT trading_date, close, adjusted_close, price_basis, fetched_at "
        "FROM price_observations ORDER BY trading_date",
    ) == [
        (
            "2026-08-19",
            "234.0",
            "233.5",
            "raw_with_crsp_adjusted_close",
            "2026-08-21T00:00:00+00:00",
        ),
        (
            "2026-08-20",
            "118.0",
            "118.0",
            "raw_with_crsp_adjusted_close",
            "2026-08-21T00:00:00+00:00",
        ),
    ]
    assert len(rows(db_path, "SELECT * FROM corporate_actions")) == 2
    assert len(rows(db_path, "SELECT * FROM raw_snapshots")) == 2
    assert rows(db_path, "SELECT status, records_accepted FROM ingestion_runs") == [
        ("succeeded", 2)
    ]
    assert all(
        "secret" not in url for (url,) in rows(db_path, "SELECT request_url FROM raw_snapshots")
    )


def test_recollecting_same_date_appends_a_new_version(tmp_path: Path) -> None:
    db_path = tmp_path / "asset_frame.sqlite3"
    collect(db_path, tmp_path / "raw", prices_body(), datetime(2026, 8, 21, tzinfo=UTC))
    revised = json.loads(prices_body())
    revised[0]["adjClose"] = 233.25
    collect(
        db_path, tmp_path / "raw", json.dumps(revised).encode(), datetime(2026, 8, 22, tzinfo=UTC)
    )

    assert rows(
        db_path,
        "SELECT fetched_at, adjusted_close FROM price_observations "
        "WHERE trading_date = '2026-08-19' ORDER BY fetched_at",
    ) == [
        ("2026-08-21T00:00:00+00:00", "233.5"),
        ("2026-08-22T00:00:00+00:00", "233.25"),
    ]
    assert rows(
        db_path,
        "SELECT count(DISTINCT raw_snapshot_id) FROM price_observations",
    ) == [(2,)]


def test_quarantined_prices_are_stored_outside_price_table(tmp_path: Path) -> None:
    db_path = tmp_path / "asset_frame.sqlite3"
    duplicate = json.loads(prices_body())
    duplicate[1]["date"] = duplicate[0]["date"]
    collect(
        db_path, tmp_path / "raw", json.dumps(duplicate).encode(), datetime(2026, 8, 21, tzinfo=UTC)
    )

    assert rows(db_path, "SELECT * FROM price_observations") == []
    quarantined = rows(db_path, "SELECT trading_date, issue_code, details FROM price_quarantine")
    assert len(quarantined) == 2
    assert {row[0] for row in quarantined} == {"2026-08-19"}
    assert all(json.loads(row[2])["issues"] for row in quarantined)
    assert rows(db_path, "SELECT records_quarantined FROM ingestion_runs") == [(2,)]

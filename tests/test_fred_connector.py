import json
import sqlite3
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from asset_frame.connectors.fred import (
    FredPayloadError,
    build_observations_request,
    parse_observations,
)
from asset_frame.domain.models import FetchResponse, RawSnapshot
from asset_frame.ingestion.fred_service import FredCollector
from asset_frame.sources.registry import load_source_registry
from asset_frame.storage.raw import FileRawStore
from asset_frame.storage.research import ResearchStore
from asset_frame.storage.sqlite import SqliteIngestionRepository


def body(observations: list[dict[str, str]], count: int | None = None) -> bytes:
    # Shape follows https://fred.stlouisfed.org/docs/api/fred/series_observations.html (json).
    return json.dumps(
        {
            "realtime_start": "2026-11-18",
            "realtime_end": "2026-11-18",
            "count": len(observations) if count is None else count,
            "offset": 0,
            "limit": 100000,
            "observations": observations,
        }
    ).encode()


ROWS = [
    {"realtime_start": "2026-11-18", "realtime_end": "2026-11-18", "date": d, "value": v}
    for d, v in [("2007-05-01", "4.80"), ("2007-05-02", "."), ("2007-05-03", "4.86")]
]
SNAPSHOT = RawSnapshot(
    uuid4(), "fred", "u", datetime(2026, 11, 18, tzinfo=UTC), 200, None, 1, "0" * 64, "x"
)


def test_request_targets_official_endpoint_and_only_approved_series() -> None:
    request = build_observations_request("DTB3", "secret")

    assert request.url.startswith("https://api.stlouisfed.org/fred/series/observations?")
    assert "series_id=DTB3" in request.url and "file_type=json" in request.url
    with pytest.raises(ValueError):
        build_observations_request("GDP", "secret")


@pytest.mark.parametrize("series_id", ["T10Y3M", "T10Y2Y", "FEDFUNDS", "DTWEXBGS", "DTWEXM"])
def test_market_rate_series_are_approved_and_read_at_the_current_vintage(series_id: str) -> None:
    url = build_observations_request(series_id, "secret").url

    assert f"series_id={series_id}" in url and "output_type" not in url


def test_only_replayed_series_request_the_initial_release() -> None:
    first = build_observations_request("INDPRO", "secret").url
    assert "output_type=4" in first and "realtime_end=9999-12-31" in first
    assert "output_type" not in build_observations_request("DTB3", "secret").url
    assert "output_type" not in build_observations_request("USREC", "secret").url


def test_first_releases_keep_the_publication_date(tmp_path: Path) -> None:
    rows = [
        {
            "realtime_start": "2026-03-17",
            "realtime_end": "2026-04-16",
            "date": "2026-02-01",
            "value": "103.5",
        },
        {
            "realtime_start": "2026-04-16",
            "realtime_end": "9999-12-31",
            "date": "2026-03-01",
            "value": ".",
        },
    ]
    fred_collector(tmp_path, rows=rows).collect(series_id="INDPRO", api_key="secret")

    assert ResearchStore(tmp_path / "db.sqlite3").macro_first_releases("INDPRO") == (
        (date(2026, 2, 1), date(2026, 3, 17), Decimal("103.5")),
        (date(2026, 3, 1), date(2026, 4, 16), None),
    )


def test_missing_value_becomes_null_not_zero() -> None:
    observations = parse_observations(body(ROWS), series_id="DTB3", snapshot=SNAPSHOT)

    assert [item.value for item in observations] == [Decimal("4.80"), None, Decimal("4.86")]
    assert observations[0].realtime_start == date(2026, 11, 18)


@pytest.mark.parametrize(
    "payload",
    [
        body(ROWS, count=5),
        body([{**ROWS[0], "value": "n/a"}]),
        body([{**ROWS[0], "value": "NaN"}]),
        b'{"error_code": 400}',
    ],
)
def test_partial_or_malformed_responses_are_rejected(payload: bytes) -> None:
    with pytest.raises(FredPayloadError):
        parse_observations(payload, series_id="DTB3", snapshot=SNAPSHOT)


class FakeTransport:
    def __init__(self, status: int = 200, rows: list[dict[str, str]] | None = None) -> None:
        self.status = status
        self.rows = ROWS if rows is None else rows

    def fetch(self, request):  # type: ignore[no-untyped-def]
        return FetchResponse(self.status, body(self.rows), {}, datetime(2026, 11, 18, tzinfo=UTC))


def fred_collector(
    tmp_path: Path, status: int = 200, rows: list[dict[str, str]] | None = None
) -> FredCollector:
    source = next(s for s in load_source_registry(Path("config/sources.toml")) if s.id == "fred")
    return FredCollector(
        source=source,
        transport=FakeTransport(status, rows),
        raw_store=FileRawStore(tmp_path / "raw"),
        repository=SqliteIngestionRepository(tmp_path / "db.sqlite3"),
    )


def test_collector_stores_rows_snapshot_and_masks_key(tmp_path: Path) -> None:
    assert fred_collector(tmp_path).collect(series_id="DTB3", api_key="secret") == 3

    with sqlite3.connect(tmp_path / "db.sqlite3") as connection:
        stored = connection.execute(
            "SELECT observation_date, value FROM macro_observation ORDER BY observation_date"
        ).fetchall()
        urls = connection.execute("SELECT request_url, sha256 FROM raw_snapshots").fetchall()
    assert stored == [("2007-05-01", "4.80"), ("2007-05-02", None), ("2007-05-03", "4.86")]
    assert len(urls) == 1 and "secret" not in urls[0][0] and len(urls[0][1]) == 64
    points = ResearchStore(tmp_path / "db.sqlite3").macro_points("DTB3")
    assert [point.value for point in points] == [Decimal("4.80"), None, Decimal("4.86")]


def test_collector_records_failed_run_on_http_error(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="HTTP 429"):
        fred_collector(tmp_path, status=429).collect(series_id="DTB3", api_key="secret")

    with sqlite3.connect(tmp_path / "db.sqlite3") as connection:
        assert connection.execute("SELECT status FROM ingestion_runs").fetchall() == [("failed",)]

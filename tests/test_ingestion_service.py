from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from asset_frame.domain.models import FetchResponse
from asset_frame.ingestion.service import SecSubmissionsCollector
from asset_frame.sources.registry import load_source_registry
from asset_frame.storage.raw import FileRawStore
from asset_frame.storage.repository import MemoryIngestionRepository


class FakeTransport:
    def __init__(self, response: FetchResponse) -> None:
        self.response = response
        self.requests = []

    def fetch(self, request):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        return self.response


def test_collection_persists_raw_before_parsed_filings(tmp_path: Path) -> None:
    source = next(
        source
        for source in load_source_registry(Path("config/sources.toml"))
        if source.id == "sec-edgar-submissions"
    )
    transport = FakeTransport(
        FetchResponse(
            status_code=200,
            body=Path("tests/fixtures/sec_submissions.json").read_bytes(),
            headers={"Content-Type": "application/json"},
            fetched_at=datetime(2026, 8, 21, tzinfo=UTC),
        )
    )
    repository = MemoryIngestionRepository()
    collector = SecSubmissionsCollector(
        source=source,
        transport=transport,
        raw_store=FileRawStore(tmp_path),
        repository=repository,
    )

    filings = collector.collect(
        cik="320193", asset_id=uuid4(), user_agent="Asset Frame admin@example.com"
    )

    assert len(filings) == 1
    assert len(repository.snapshots) == 1
    assert len(repository.filings) == 1
    assert transport.requests[0].url.endswith("CIK0000320193.json")
    run_id, run = next(iter(repository.ingestion_runs.items()))
    assert run["source_id"] == "sec-edgar-submissions"
    assert run["data_kind"] == "filing"
    assert run["status"] == "succeeded"
    assert run["records_received"] == 1
    assert run["records_accepted"] == 1
    assert run["records_quarantined"] == 0
    assert next(iter(repository.snapshots.values())).ingestion_run_id == run_id


def test_collection_records_failed_run_for_http_error(tmp_path: Path) -> None:
    source = next(
        source
        for source in load_source_registry(Path("config/sources.toml"))
        if source.id == "sec-edgar-submissions"
    )
    repository = MemoryIngestionRepository()
    collector = SecSubmissionsCollector(
        source=source,
        transport=FakeTransport(
            FetchResponse(
                status_code=503,
                body=b"unavailable",
                headers={"Content-Type": "text/plain"},
                fetched_at=datetime(2026, 8, 21, tzinfo=UTC),
            )
        ),
        raw_store=FileRawStore(tmp_path),
        repository=repository,
    )

    with pytest.raises(RuntimeError, match="503"):
        collector.collect(
            cik="320193", asset_id=uuid4(), user_agent="Asset Frame admin@example.com"
        )

    run = next(iter(repository.ingestion_runs.values()))
    assert run["status"] == "failed"
    assert run["error_code"] == "IngestionError"
    assert repository.snapshots == {}

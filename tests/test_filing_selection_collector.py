import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from asset_frame.domain.models import FetchResponse
from asset_frame.ingestion.service import SecSubmissionsCollector
from asset_frame.sources.registry import load_source_registry
from asset_frame.storage.raw import FileRawStore
from asset_frame.storage.repository import MemoryIngestionRepository


class StaticTransport:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def fetch(self, request):  # type: ignore[no-untyped-def]
        return FetchResponse(
            status_code=200,
            body=self.body,
            headers={"Content-Type": "application/json"},
            fetched_at=datetime(2026, 8, 21, tzinfo=UTC),
        )


def test_sec_collector_counts_received_and_selected_filings(tmp_path: Path) -> None:
    body = json.dumps(
        {
            "cik": "320193",
            "filings": {
                "recent": {
                    "accessionNumber": ["0000320193-26-000001", "0000320193-26-000002"],
                    "filingDate": ["2026-08-20", "2026-08-21"],
                    "form": ["10-Q", "4"],
                    "primaryDocument": ["quarterly.htm", "ownership.htm"],
                }
            },
        }
    ).encode()
    source = next(
        item
        for item in load_source_registry(Path("config/sources.toml"))
        if item.id == "sec-edgar-submissions"
    )
    repository = MemoryIngestionRepository()
    collector = SecSubmissionsCollector(
        source=source,
        transport=StaticTransport(body),
        raw_store=FileRawStore(tmp_path),
        repository=repository,
    )

    selected = collector.collect(
        cik="320193", asset_id=uuid4(), user_agent="Asset Frame admin@example.com"
    )

    assert [item.form_type for item in selected] == ["10-Q"]
    run = next(iter(repository.ingestion_runs.values()))
    assert run["records_received"] == 2
    assert run["records_accepted"] == 1

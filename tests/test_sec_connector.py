import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from asset_frame.connectors.sec import (
    SecPayloadError,
    build_submissions_request,
    normalize_cik,
    parse_recent_filings,
)
from asset_frame.domain.models import RawSnapshot


def make_snapshot() -> RawSnapshot:
    return RawSnapshot(
        id=uuid4(),
        source_id="sec-edgar-submissions",
        request_url="https://data.sec.gov/submissions/CIK0000320193.json",
        fetched_at=datetime(2026, 8, 21, tzinfo=UTC),
        http_status=200,
        content_type="application/json",
        content_length=1,
        sha256="0" * 64,
        storage_path="raw.bin",
    )


def test_build_request_normalizes_cik_and_sets_identity() -> None:
    request = build_submissions_request("320193", "Asset Frame admin@example.com")

    assert request.url.endswith("CIK0000320193.json")
    assert request.headers["User-Agent"] == "Asset Frame admin@example.com"


@pytest.mark.parametrize("value", ["", "12345678901", "12A", "１２３"])
def test_invalid_cik_is_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_cik(value)


def test_parse_recent_filings_keeps_source_lineage() -> None:
    body = Path("tests/fixtures/sec_submissions.json").read_bytes()
    snapshot = make_snapshot()

    filings = parse_recent_filings(body, asset_id=uuid4(), snapshot=snapshot)

    assert len(filings) == 1
    assert filings[0].raw_snapshot_id == snapshot.id
    assert filings[0].accession_number == "0000320193-26-000001"
    assert filings[0].document_url == (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019326000001/example-20260630.htm"
    )


def test_parse_recent_filing_without_primary_document_uses_accession_directory() -> None:
    payload = {
        "cik": "884394",
        "filings": {
            "recent": {
                "accessionNumber": ["0001193125-00-000001"],
                "filingDate": ["2000-01-03"],
                "form": ["24F-2NT"],
                "primaryDocument": [""],
            }
        },
    }

    filing = parse_recent_filings(
        json.dumps(payload).encode(), asset_id=uuid4(), snapshot=make_snapshot()
    )[0]

    assert filing.primary_document is None
    assert filing.document_url == (
        "https://www.sec.gov/Archives/edgar/data/884394/000119312500000001/"
    )


def test_malformed_payload_is_rejected() -> None:
    with pytest.raises(SecPayloadError):
        parse_recent_filings(b"{}", asset_id=uuid4(), snapshot=make_snapshot())

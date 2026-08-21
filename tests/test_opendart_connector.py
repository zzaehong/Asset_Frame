import json
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from asset_frame.connectors.opendart import (
    OpenDartPayloadError,
    build_disclosure_request,
    parse_disclosure_page,
)
from asset_frame.domain.models import FetchResponse, RawSnapshot
from asset_frame.ingestion.opendart_service import OpenDartDisclosureCollector
from asset_frame.ingestion.security import mask_url_secrets
from asset_frame.sources.registry import load_source_registry
from asset_frame.storage.raw import FileRawStore
from asset_frame.storage.repository import MemoryIngestionRepository


def snapshot() -> RawSnapshot:
    return RawSnapshot(
        uuid4(),
        "opendart",
        "https://opendart.fss.or.kr/api/list.json?crtfc_key=***",
        datetime(2026, 8, 21, tzinfo=UTC),
        200,
        "application/json",
        1,
        "0" * 64,
        "raw.bin",
    )


def disclosure_body(*, page_no: int = 1, total_page: int = 1) -> bytes:
    return json.dumps(
        {
            "status": "000",
            "message": "정상",
            "page_no": page_no,
            "page_count": 100,
            "total_count": 1,
            "total_page": total_page,
            "list": [
                {
                    "corp_code": "00126380",
                    "corp_name": "삼성전자",
                    "stock_code": "005930",
                    "corp_cls": "Y",
                    "report_nm": "사업보고서 (2025.12)",
                    "rcept_no": f"20260318000{page_no:03d}",
                    "flr_nm": "삼성전자",
                    "rcept_dt": "20260318",
                    "rm": "",
                }
            ],
        },
        ensure_ascii=False,
    ).encode()


def test_request_uses_official_endpoint_and_masks_api_key() -> None:
    request = build_disclosure_request(
        api_key="secret",
        corp_code="00126380",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 8, 21),
        page_no=1,
    )

    assert request.url.startswith("https://opendart.fss.or.kr/api/list.json?")
    assert "corp_code=00126380" in request.url
    masked = mask_url_secrets(request.url)
    assert "secret" not in masked
    assert "crtfc_key=%2A%2A%2A" in masked


def test_parse_disclosure_maps_filing_and_lineage() -> None:
    raw_snapshot = snapshot()
    parsed = parse_disclosure_page(
        disclosure_body(),
        asset_id=uuid4(),
        snapshot=raw_snapshot,
        expected_corp_code="00126380",
    )

    assert parsed.total_pages == 1
    assert parsed.filings[0].accession_number == "20260318000001"
    assert parsed.filings[0].filed_at == date(2026, 3, 18)
    assert parsed.filings[0].raw_snapshot_id == raw_snapshot.id
    assert parsed.filings[0].document_url.endswith("rcpNo=20260318000001")


def test_parse_disclosure_rejects_api_error_and_wrong_corp_code() -> None:
    with pytest.raises(OpenDartPayloadError, match="010"):
        parse_disclosure_page(
            json.dumps({"status": "010", "message": "등록되지 않은 키"}).encode(),
            asset_id=uuid4(),
            snapshot=snapshot(),
            expected_corp_code="00126380",
        )
    with pytest.raises(OpenDartPayloadError, match="corp_code"):
        parse_disclosure_page(
            disclosure_body(),
            asset_id=uuid4(),
            snapshot=snapshot(),
            expected_corp_code="00000000",
        )


class PageTransport:
    def __init__(self) -> None:
        self.page = 0

    def fetch(self, request):  # type: ignore[no-untyped-def]
        self.page += 1
        return FetchResponse(
            status_code=200,
            body=disclosure_body(page_no=self.page, total_page=2),
            headers={"Content-Type": "application/json"},
            fetched_at=datetime(2026, 8, 21, tzinfo=UTC),
        )


def test_collector_preserves_each_page_and_saves_all_filings(tmp_path: Path) -> None:
    source = next(
        source
        for source in load_source_registry(Path("config/sources.toml"))
        if source.id == "opendart"
    )
    repository = MemoryIngestionRepository()
    collector = OpenDartDisclosureCollector(
        source=source,
        transport=PageTransport(),
        raw_store=FileRawStore(tmp_path),
        repository=repository,
    )

    filings = collector.collect(
        api_key="secret",
        corp_code="00126380",
        asset_id=uuid4(),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 8, 21),
    )

    assert len(filings) == 2
    assert len(repository.snapshots) == 2
    assert len(repository.filings) == 2
    assert all("secret" not in item.request_url for item in repository.snapshots.values())

import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from asset_frame.connectors.opendart import (
    OpenDartPayloadError,
    build_corp_code_request,
    parse_corp_code_archive,
)
from asset_frame.connectors.sec import (
    SecPayloadError,
    build_ticker_mapping_request,
    parse_ticker_mapping,
)
from asset_frame.connectors.tiingo import tiingo_asset_id
from asset_frame.domain.models import (
    Asset,
    AssetIdentifier,
    AssetType,
    FetchResponse,
    IdentifierType,
)
from asset_frame.ingestion.identifier_service import RegulatoryIdentifierCollector
from asset_frame.sources.registry import load_source_registry
from asset_frame.storage.raw import FileRawStore
from asset_frame.storage.repository import MemoryIngestionRepository


def sec_mapping_body() -> bytes:
    return json.dumps(
        {
            "fields": ["cik", "name", "ticker", "exchange"],
            "data": [
                [320193, "Apple Inc.", "AAPL", "Nasdaq"],
                [789019, "Microsoft Corp", "MSFT", "Nasdaq"],
                [1, "No Exchange Corp", "NOEX", None],
            ],
        }
    ).encode()


def dart_mapping_body() -> bytes:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<result>
  <list><corp_code>00126380</corp_code><corp_name>삼성전자</corp_name>
    <stock_code>005930</stock_code><modify_date>20260820</modify_date></list>
  <list><corp_code>00164779</corp_code><corp_name>SK하이닉스</corp_name>
    <stock_code>000660</stock_code><modify_date>20260819</modify_date></list>
  <list><corp_code>01933981</corp_code><corp_name>비엔케이제3호스팩</corp_name>
    <stock_code>0068Y0</stock_code><modify_date>20260821</modify_date></list>
  <list><corp_code>00999999</corp_code><corp_name>비상장사</corp_name>
    <stock_code></stock_code><modify_date>20260818</modify_date></list>
</result>""".encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("CORPCODE.xml", xml)
    return output.getvalue()


def test_sec_mapping_request_and_parser() -> None:
    request = build_ticker_mapping_request("Asset Frame admin@example.com")
    records = parse_ticker_mapping(sec_mapping_body())

    assert request.url == "https://www.sec.gov/files/company_tickers_exchange.json"
    assert records[0].ticker == "AAPL"
    assert records[0].identifier_value == "0000320193"
    assert records[0].exchange_code == "Nasdaq"
    assert records[2].exchange_code is None


def test_sec_mapping_rejects_schema_and_conflicting_ticker() -> None:
    with pytest.raises(SecPayloadError, match="schema"):
        parse_ticker_mapping(json.dumps({"fields": [], "data": []}).encode())
    payload = json.loads(sec_mapping_body())
    payload["data"].append([2, "Conflict", "AAPL", "NYSE"])
    with pytest.raises(SecPayloadError, match="multiple CIKs"):
        parse_ticker_mapping(json.dumps(payload).encode())


def test_opendart_mapping_request_parser_and_secret_masking(tmp_path: Path) -> None:
    request = build_corp_code_request("secret")
    records = parse_corp_code_archive(dart_mapping_body())

    assert request.url.startswith("https://opendart.fss.or.kr/api/corpCode.xml?")
    assert len(records) == 3
    assert records[0].ticker == "005930"
    assert records[0].identifier_value == "00126380"
    assert records[0].modified_at.isoformat() == "2026-08-20"
    assert records[2].ticker == "0068Y0"

    snapshot = FileRawStore(tmp_path).save(
        snapshot_id=tiingo_asset_id("MASK-TEST"),
        source_id="opendart",
        request_url=request.url,
        response=FetchResponse(
            200,
            dart_mapping_body(),
            {"Content-Type": "application/zip"},
            datetime(2026, 8, 21, tzinfo=UTC),
        ),
    )
    assert "secret" not in snapshot.request_url


def test_opendart_mapping_rejects_invalid_archive() -> None:
    with pytest.raises(OpenDartPayloadError, match="archive"):
        parse_corp_code_archive(b"not-a-zip")


class FakeTransport:
    def __init__(self, body: bytes, content_type: str) -> None:
        self.body = body
        self.content_type = content_type

    def fetch(self, request):  # type: ignore[no-untyped-def]
        return FetchResponse(
            200,
            self.body,
            {"Content-Type": self.content_type},
            datetime(2026, 8, 21, tzinfo=UTC),
        )


def test_sec_collector_maps_only_exact_existing_tickers(tmp_path: Path) -> None:
    source = next(
        source
        for source in load_source_registry(Path("config/sources.toml"))
        if source.id == "sec-edgar-submissions"
    )
    repository = MemoryIngestionRepository()
    apple_id = tiingo_asset_id("AAPL")
    missing_id = tiingo_asset_id("MISSING")
    repository.upsert_assets(
        (
            Asset(apple_id, "Apple Inc", AssetType.EQUITY, "US", "USD"),
            Asset(missing_id, "Missing", AssetType.EQUITY, "US", "USD"),
        ),
        (
            AssetIdentifier(apple_id, IdentifierType.TICKER, "AAPL"),
            AssetIdentifier(missing_id, IdentifierType.TICKER, "MISSING"),
        ),
    )
    collector = RegulatoryIdentifierCollector(
        source=source,
        country_code="US",
        target_identifier_type=IdentifierType.CIK,
        transport=FakeTransport(sec_mapping_body(), "application/json"),
        raw_store=FileRawStore(tmp_path),
        repository=repository,
    )

    result = collector.collect_sec(user_agent="Asset Frame admin@example.com")

    assert result.records_received == 3
    assert result.assets_considered == 2
    assert result.assets_mapped == 1
    assert result.assets_missing == ("MISSING",)
    assert AssetIdentifier(apple_id, IdentifierType.CIK, "0000320193") in repository.identifiers
    run_id, run = next(iter(repository.ingestion_runs.items()))
    assert run["status"] == "succeeded"
    assert run["data_kind"] == "asset_identifier"
    assert run["records_received"] == 3
    assert run["records_accepted"] == 1
    assert next(iter(repository.snapshots.values())).ingestion_run_id == run_id

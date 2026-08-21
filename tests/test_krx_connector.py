import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from asset_frame.connectors.krx import KrxDataset, build_request, parse_assets, parse_prices
from asset_frame.domain.models import AssetType, FetchResponse, RawSnapshot
from asset_frame.ingestion.krx_service import KrxCollector
from asset_frame.sources.registry import load_source_registry
from asset_frame.storage.raw import FileRawStore
from asset_frame.storage.repository import MemoryIngestionRepository


def snapshot() -> RawSnapshot:
    return RawSnapshot(
        uuid4(),
        "krx-open-api",
        "https://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd?basDd=20260819",
        datetime(2026, 8, 19, tzinfo=UTC),
        200,
        "application/json",
        1,
        "0" * 64,
        "raw.bin",
    )


def test_request_uses_official_endpoint_and_auth_header() -> None:
    request = build_request(KrxDataset.KOSPI_PRICES, date(2026, 8, 19), "secret")

    assert request.url.endswith("/sto/stk_bydd_trd?basDd=20260819")
    assert request.headers["AUTH_KEY"] == "secret"
    assert "secret" not in request.url


def test_parse_price_preserves_raw_price_basis() -> None:
    body = json.dumps(
        {
            "OutBlock_1": [
                {
                    "BAS_DD": "20260819",
                    "ISU_CD": "005930",
                    "ISU_NM": "삼성전자",
                    "TDD_CLSPRC": "100000",
                    "TDD_OPNPRC": "99000",
                    "TDD_HGPRC": "101000",
                    "TDD_LWPRC": "98000",
                    "ACC_TRDVOL": "123456",
                }
            ]
        }
    ).encode()

    assets, identifiers, prices = parse_prices(
        body, snapshot=snapshot(), asset_type=AssetType.EQUITY
    )

    assert assets[0].name == "삼성전자"
    assert identifiers[0].value == "005930"
    assert prices[0].close == Decimal("100000")
    assert prices[0].adjusted_close is None
    assert prices[0].price_basis == "raw"


def test_parse_base_info_maps_ticker_and_isin() -> None:
    body = json.dumps(
        {
            "OutBlock_1": [
                {
                    "ISU_CD": "KR7005930003",
                    "ISU_SRT_CD": "005930",
                    "ISU_ABBRV": "삼성전자",
                    "MKT_TP_NM": "KOSPI",
                }
            ]
        }
    ).encode()

    parsed = parse_assets(body)

    assert {identifier.value for identifier in parsed.identifiers} == {
        "005930",
        "KR7005930003",
        "KOSPI",
    }


class FakeTransport:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def fetch(self, request):  # type: ignore[no-untyped-def]
        return FetchResponse(
            status_code=200,
            body=self.body,
            headers={"Content-Type": "application/json"},
            fetched_at=datetime(2026, 8, 19, tzinfo=UTC),
        )


def test_collector_quarantines_duplicate_and_wrong_date_rows(tmp_path) -> None:
    row = {
        "BAS_DD": "20260818",
        "ISU_CD": "005930",
        "ISU_NM": "삼성전자",
        "TDD_CLSPRC": "100000",
        "TDD_OPNPRC": "99000",
        "TDD_HGPRC": "101000",
        "TDD_LWPRC": "98000",
        "ACC_TRDVOL": "123456",
    }
    body = json.dumps({"OutBlock_1": [row, row]}).encode()
    source = next(
        source
        for source in load_source_registry(Path("config/sources.toml"))
        if source.id == "krx-open-api"
    )
    repository = MemoryIngestionRepository()
    collector = KrxCollector(
        source=source,
        transport=FakeTransport(body),
        raw_store=FileRawStore(tmp_path),
        repository=repository,
    )

    accepted = collector.collect(
        dataset=KrxDataset.KOSPI_PRICES,
        business_date=date(2026, 8, 19),
        api_key="secret",
    )

    assert accepted == 0
    assert repository.prices == []
    assert len(repository.quarantined_prices) == 2
    issue_codes = {
        issue["code"] for item in repository.quarantined_prices for issue in item.details["issues"]
    }
    assert issue_codes == {"business_date_mismatch", "duplicate_asset_date"}

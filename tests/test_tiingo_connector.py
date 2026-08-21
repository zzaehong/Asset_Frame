import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from asset_frame.connectors.tiingo import (
    TiingoPayloadError,
    build_metadata_request,
    build_prices_request,
    parse_metadata,
    parse_prices,
)
from asset_frame.domain.models import AssetType, FetchResponse, RawSnapshot
from asset_frame.ingestion.tiingo_service import TiingoEodCollector
from asset_frame.sources.registry import load_source_registry
from asset_frame.storage.raw import FileRawStore
from asset_frame.storage.repository import MemoryIngestionRepository


def snapshot() -> RawSnapshot:
    return RawSnapshot(
        uuid4(),
        "tiingo-eod",
        "https://api.tiingo.com/tiingo/daily/AAPL/prices",
        datetime(2026, 8, 21, tzinfo=UTC),
        200,
        "application/json",
        1,
        "0" * 64,
        "raw.bin",
    )


def metadata_body() -> bytes:
    return json.dumps(
        {
            "ticker": "AAPL",
            "name": "Apple Inc",
            "exchangeCode": "NASDAQ",
            "description": "Consumer electronics company",
            "startDate": "1980-12-12",
            "endDate": "2026-08-20",
        }
    ).encode()


def prices_body() -> bytes:
    return json.dumps(
        [
            {
                "date": "2026-08-19T00:00:00.000Z",
                "open": 230.0,
                "high": 235.0,
                "low": 229.0,
                "close": 234.0,
                "volume": 1000,
                "adjOpen": 229.5,
                "adjHigh": 234.5,
                "adjLow": 228.5,
                "adjClose": 233.5,
                "adjVolume": 1000,
                "divCash": 0.25,
                "splitFactor": 1.0,
            },
            {
                "date": "2026-08-20T00:00:00.000Z",
                "open": 117.0,
                "high": 119.0,
                "low": 116.0,
                "close": 118.0,
                "volume": 2000,
                "adjOpen": 117.0,
                "adjHigh": 119.0,
                "adjLow": 116.0,
                "adjClose": 118.0,
                "adjVolume": 2000,
                "divCash": 0.0,
                "splitFactor": 2.0,
            },
        ]
    ).encode()


def test_requests_use_official_endpoints_and_authorization_header() -> None:
    metadata = build_metadata_request("aapl", "secret")
    prices = build_prices_request(
        "aapl",
        api_key="secret",
        start_date=date(2026, 8, 19),
        end_date=date(2026, 8, 20),
    )

    assert metadata.url == "https://api.tiingo.com/tiingo/daily/AAPL"
    assert "startDate=2026-08-19" in prices.url
    assert "secret" not in metadata.url
    assert "secret" not in prices.url
    assert metadata.headers["Authorization"] == "Token secret"


def test_metadata_requires_matching_ticker_and_explicit_asset_type() -> None:
    parsed = parse_metadata(metadata_body(), expected_ticker="AAPL", asset_type=AssetType.EQUITY)

    assert parsed.asset.name == "Apple Inc"
    assert parsed.asset.asset_type is AssetType.EQUITY
    assert parsed.asset.country_code == "US"
    assert {identifier.value for identifier in parsed.identifiers} == {"AAPL", "NASDAQ"}

    with pytest.raises(TiingoPayloadError, match="does not match"):
        parse_metadata(metadata_body(), expected_ticker="MSFT", asset_type=AssetType.EQUITY)


def test_prices_preserve_raw_adjusted_and_corporate_actions() -> None:
    parsed = parse_prices(
        prices_body(),
        asset_id=uuid4(),
        snapshot=snapshot(),
        start_date=date(2026, 8, 19),
        end_date=date(2026, 8, 20),
    )

    assert parsed.prices[0].close == Decimal("234.0")
    assert parsed.prices[0].adjusted_close == Decimal("233.5")
    assert parsed.prices[0].price_basis == "raw_with_crsp_adjusted_close"
    assert [action.action_type for action in parsed.corporate_actions] == [
        "cash_dividend",
        "split",
    ]
    assert parsed.corporate_actions[1].ratio_numerator == Decimal("2.0")


def test_prices_reject_out_of_range_and_non_finite_values() -> None:
    payload = json.loads(prices_body())
    payload[0]["date"] = "2026-08-18T00:00:00.000Z"
    with pytest.raises(TiingoPayloadError, match="outside"):
        parse_prices(
            json.dumps(payload).encode(),
            asset_id=uuid4(),
            snapshot=snapshot(),
            start_date=date(2026, 8, 19),
            end_date=date(2026, 8, 20),
        )

    payload = json.loads(prices_body())
    payload[0]["close"] = "NaN"
    with pytest.raises(TiingoPayloadError, match="finite"):
        parse_prices(
            json.dumps(payload).encode(),
            asset_id=uuid4(),
            snapshot=snapshot(),
            start_date=date(2026, 8, 19),
            end_date=date(2026, 8, 20),
        )


class FakeTransport:
    def __init__(self, responses: list[bytes]) -> None:
        self.responses = responses
        self.requests = []

    def fetch(self, request):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        return FetchResponse(
            status_code=200,
            body=self.responses.pop(0),
            headers={"Content-Type": "application/json"},
            fetched_at=datetime(2026, 8, 21, tzinfo=UTC),
        )


def test_collector_saves_metadata_prices_actions_and_two_snapshots(tmp_path: Path) -> None:
    source = next(
        source
        for source in load_source_registry(Path("config/sources.toml"))
        if source.id == "tiingo-eod"
    )
    repository = MemoryIngestionRepository()
    transport = FakeTransport([metadata_body(), prices_body()])
    collector = TiingoEodCollector(
        source=source,
        transport=transport,
        raw_store=FileRawStore(tmp_path),
        repository=repository,
    )

    result = collector.collect(
        ticker="AAPL",
        asset_type=AssetType.EQUITY,
        api_key="secret",
        start_date=date(2026, 8, 19),
        end_date=date(2026, 8, 20),
    )

    assert result.accepted_prices == 2
    assert result.quarantined_prices == 0
    assert result.corporate_actions == 2
    assert len(repository.snapshots) == 2
    assert len(repository.assets) == 1
    assert len(repository.prices) == 2
    assert len(repository.corporate_actions) == 2
    assert all("secret" not in item.request_url for item in repository.snapshots.values())


def test_collector_quarantines_all_duplicate_dates_and_related_actions(tmp_path: Path) -> None:
    duplicate_rows = json.loads(prices_body())
    duplicate_rows[1]["date"] = duplicate_rows[0]["date"]
    source = next(
        source
        for source in load_source_registry(Path("config/sources.toml"))
        if source.id == "tiingo-eod"
    )
    repository = MemoryIngestionRepository()
    collector = TiingoEodCollector(
        source=source,
        transport=FakeTransport([metadata_body(), json.dumps(duplicate_rows).encode()]),
        raw_store=FileRawStore(tmp_path),
        repository=repository,
    )

    result = collector.collect(
        ticker="AAPL",
        asset_type=AssetType.EQUITY,
        api_key="secret",
        start_date=date(2026, 8, 19),
        end_date=date(2026, 8, 20),
    )

    assert result.accepted_prices == 0
    assert result.quarantined_prices == 2
    assert result.corporate_actions == 0
    assert repository.prices == []
    assert repository.corporate_actions == []

from datetime import UTC, date, datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile

from asset_frame.connectors.tiingo import tiingo_asset_id
from asset_frame.domain.models import Asset, AssetType, FetchResponse
from asset_frame.ingestion.market_batch import TiingoMarketBatchService, ten_year_start
from asset_frame.ingestion.universe import UniverseMembership
from asset_frame.sources.registry import load_source_registry
from asset_frame.storage.raw import FileRawStore
from asset_frame.storage.repository import MemoryIngestionRepository


class StaticTransport:
    def __init__(self, response: FetchResponse) -> None:
        self.response = response

    def fetch(self, request):  # type: ignore[no-untyped-def]
        return self.response


class RecordingBatchRepository:
    def __init__(self) -> None:
        self.job_id = UUID(int=99)
        self.prepared = None

    def prepare_job(self, **kwargs):  # type: ignore[no-untyped-def]
        self.prepared = kwargs
        return self.job_id


class StaticUniverseRepository:
    def latest_memberships(self, **kwargs):  # type: ignore[no-untyped-def]
        return (
            UniverseMembership(
                asset_id=UUID(int=1),
                ticker="AAPL",
                asset_type=AssetType.EQUITY,
                selected_rank=1,
                median_dollar_volume=Decimal("100"),
                observation_count=60,
                pinned=False,
                selection_reason="median_dollar_volume",
            ),
        )


def _archive() -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "supported_tickers.csv",
            "ticker,exchange,assetType,priceCurrency,startDate,endDate\n"
            "AAPL,NASDAQ,Stock,USD,1980-12-12,2026-08-21\n"
            "SPY,NYSE ARCA,ETF,USD,1993-01-29,2026-08-21\n"
            "OTC,PINK,Stock,USD,2000-01-01,2026-08-21\n",
        )
    return output.getvalue()


def test_prepares_discovery_assets_and_checkpoint_items(tmp_path: Path) -> None:
    source = next(
        item
        for item in load_source_registry(Path("config/sources.toml"))
        if item.id == "tiingo-eod"
    )
    ingestion = MemoryIngestionRepository()
    ingestion.upsert_assets(
        (
            Asset(
                tiingo_asset_id("AAPL"),
                "Apple Inc.",
                AssetType.EQUITY,
                "US",
                "USD",
            ),
        ),
        (),
    )
    batches = RecordingBatchRepository()
    service = TiingoMarketBatchService(
        source=source,
        transport=StaticTransport(
            FetchResponse(
                200,
                _archive(),
                {"Content-Type": "application/zip"},
                datetime(2026, 8, 21, tzinfo=UTC),
            )
        ),
        raw_store=FileRawStore(tmp_path),
        ingestion_repository=ingestion,
        batch_repository=batches,  # type: ignore[arg-type]
    )

    job_id = service.prepare_discovery(
        as_of_date=date(2026, 8, 21),
        start_date=date(2026, 5, 23),
        end_date=date(2026, 8, 21),
    )

    assert job_id == UUID(int=99)
    assert {asset.name for asset in ingestion.assets.values()} == {"Apple Inc.", "SPY"}
    assert [item.ticker for item in batches.prepared["items"]] == ["AAPL", "SPY"]
    assert next(iter(ingestion.ingestion_runs.values()))["status"] == "succeeded"


def test_ten_year_start_handles_leap_day() -> None:
    assert ten_year_start(date(2024, 2, 29)) == date(2014, 2, 28)


def test_prepares_backfill_from_latest_universe(tmp_path: Path) -> None:
    source = next(
        item
        for item in load_source_registry(Path("config/sources.toml"))
        if item.id == "tiingo-eod"
    )
    batches = RecordingBatchRepository()
    service = TiingoMarketBatchService(
        source=source,
        transport=StaticTransport(FetchResponse(200, b"", {}, datetime(2026, 8, 21, tzinfo=UTC))),
        raw_store=FileRawStore(tmp_path),
        ingestion_repository=MemoryIngestionRepository(),
        batch_repository=batches,  # type: ignore[arg-type]
        universe_repository=StaticUniverseRepository(),  # type: ignore[arg-type]
    )

    job_id = service.prepare_universe_backfill(
        as_of_date=date(2026, 8, 21),
        start_date=date(2021, 8, 21),
        end_date=date(2026, 8, 21),
    )

    assert job_id == UUID(int=99)
    assert batches.prepared["job_type"] == "universe_backfill"
    assert [item.ticker for item in batches.prepared["items"]] == ["AAPL"]

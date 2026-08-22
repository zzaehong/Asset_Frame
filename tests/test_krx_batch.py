from datetime import date
from pathlib import Path
from uuid import UUID

from asset_frame.connectors.krx import KrxDataset
from asset_frame.ingestion.krx_batch import KrxMarketBatchService, krx_backfill_items
from asset_frame.sources.registry import load_source_registry
from asset_frame.storage.krx_batch import KrxBackfillItem, KrxBackfillJob
from asset_frame.storage.repository import MemoryIngestionRepository


class RecordingCollector:
    def collect(self, *, dataset, business_date, api_key):  # type: ignore[no-untyped-def]
        if dataset is KrxDataset.ETF_PRICES:
            return 0
        return 10


class RecordingBatchRepository:
    def __init__(self) -> None:
        self.id = UUID(int=88)
        self.prepared = None
        self.completed = []
        self.failed = []

    def prepare_job(self, **kwargs):  # type: ignore[no-untyped-def]
        self.prepared = kwargs
        return self.id

    def get_job(self, job_id):  # type: ignore[no-untyped-def]
        return KrxBackfillJob(
            job_id,
            "krx-open-api",
            date(2026, 8, 21),
            date(2026, 8, 21),
            date(2026, 8, 21),
            "pending",
        )

    def claim_items(self, **kwargs):  # type: ignore[no-untyped-def]
        return (
            KrxBackfillItem(date(2026, 8, 21), KrxDataset.KOSPI_PRICES),
            KrxBackfillItem(date(2026, 8, 21), KrxDataset.ETF_PRICES),
        )

    def complete_item(self, **kwargs):  # type: ignore[no-untyped-def]
        self.completed.append(kwargs)

    def fail_item(self, **kwargs):  # type: ignore[no-untyped-def]
        self.failed.append(kwargs)

    def refresh_job_status(self, job_id):  # type: ignore[no-untyped-def]
        return None


def _service(repository: RecordingBatchRepository) -> KrxMarketBatchService:
    source = next(
        item
        for item in load_source_registry(Path("config/sources.toml"))
        if item.id == "krx-open-api"
    )
    return KrxMarketBatchService(
        source=source,
        collector=RecordingCollector(),  # type: ignore[arg-type]
        ingestion_repository=MemoryIngestionRepository(),
        batch_repository=repository,  # type: ignore[arg-type]
    )


def test_backfill_items_exclude_weekends_and_cover_three_markets() -> None:
    items = krx_backfill_items(date(2026, 8, 21), date(2026, 8, 24))

    assert len(items) == 6
    assert {item.business_date for item in items} == {date(2026, 8, 21), date(2026, 8, 24)}
    assert {item.dataset for item in items} == {
        KrxDataset.KOSPI_PRICES,
        KrxDataset.KOSDAQ_PRICES,
        KrxDataset.ETF_PRICES,
    }


def test_prepare_and_run_distinguish_no_data() -> None:
    repository = RecordingBatchRepository()
    service = _service(repository)
    job_id = service.prepare(
        as_of_date=date(2026, 8, 21),
        start_date=date(2026, 8, 21),
        end_date=date(2026, 8, 21),
    )
    result = service.run(job_id=job_id, api_key="test", max_items=2, retry_failed=False)

    assert len(repository.prepared["items"]) == 3
    assert result.attempted == 2
    assert result.succeeded == 1
    assert result.no_data == 1
    assert result.records_accepted == 10

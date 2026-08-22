from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from asset_frame.connectors.krx import KRX_SOURCE_ID, KrxDataset
from asset_frame.domain.models import ImplementationStatus, SourceDefinition
from asset_frame.ingestion.krx_service import KrxCollector
from asset_frame.storage.krx_batch import KrxBackfillItem, PostgresKrxBatchRepository
from asset_frame.storage.repository import IngestionRepository

PRICE_DATASETS = (
    KrxDataset.KOSPI_PRICES,
    KrxDataset.KOSDAQ_PRICES,
    KrxDataset.ETF_PRICES,
)


@dataclass(frozen=True, slots=True)
class KrxBatchResult:
    attempted: int
    succeeded: int
    no_data: int
    failed: int
    records_accepted: int


def krx_backfill_items(start_date: date, end_date: date) -> tuple[KrxBackfillItem, ...]:
    if start_date > end_date:
        raise ValueError("KRX backfill start date must not exceed end date")
    items: list[KrxBackfillItem] = []
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:
            items.extend(KrxBackfillItem(current, dataset) for dataset in PRICE_DATASETS)
        current += timedelta(days=1)
    return tuple(items)


class KrxMarketBatchService:
    def __init__(
        self,
        *,
        source: SourceDefinition,
        collector: KrxCollector,
        ingestion_repository: IngestionRepository,
        batch_repository: PostgresKrxBatchRepository,
    ) -> None:
        if source.id != KRX_SOURCE_ID:
            raise ValueError("KRX batch service requires the KRX source definition")
        if not source.enabled or source.implementation_status is not ImplementationStatus.AVAILABLE:
            raise ValueError("KRX source is not available and enabled")
        self._source = source
        self._collector = collector
        self._ingestion_repository = ingestion_repository
        self._batch_repository = batch_repository

    def prepare(self, *, as_of_date: date, start_date: date, end_date: date) -> UUID:
        self._ingestion_repository.upsert_source(self._source)
        return self._batch_repository.prepare_job(
            source_id=self._source.id,
            as_of_date=as_of_date,
            start_date=start_date,
            end_date=end_date,
            items=krx_backfill_items(start_date, end_date),
        )

    def run(
        self, *, job_id: UUID, api_key: str, max_items: int, retry_failed: bool
    ) -> KrxBatchResult:
        if max_items <= 0:
            raise ValueError("max_items must be positive")
        job = self._batch_repository.get_job(job_id)
        if job.source_id != self._source.id:
            raise ValueError("backfill job is not a KRX job")
        items = self._batch_repository.claim_items(
            job_id=job_id, limit=max_items, retry_failed=retry_failed
        )
        succeeded = no_data = failed = records_accepted = 0
        for item in items:
            try:
                accepted = self._collector.collect(
                    dataset=item.dataset,
                    business_date=item.business_date,
                    api_key=api_key,
                )
            except Exception as error:  # noqa: BLE001 - one date must not abort the batch
                self._batch_repository.fail_item(
                    job_id=job_id,
                    item=item,
                    error_message=f"{type(error).__name__}: {error}",
                )
                failed += 1
                continue
            self._batch_repository.complete_item(
                job_id=job_id, item=item, records_accepted=accepted
            )
            if accepted:
                succeeded += 1
            else:
                no_data += 1
            records_accepted += accepted
        self._batch_repository.refresh_job_status(job_id)
        return KrxBatchResult(len(items), succeeded, no_data, failed, records_accepted)

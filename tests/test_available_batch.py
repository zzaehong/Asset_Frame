from datetime import date
from uuid import UUID

from asset_frame.domain.models import Asset, AssetIdentifier, AssetType, IdentifierType
from asset_frame.ingestion.available_batch import AvailableUniverseCollectionService
from asset_frame.ingestion.universe import UniverseMembership
from asset_frame.storage.collection_batch import (
    UniverseCollectionItem,
    UniverseCollectionJob,
)
from asset_frame.storage.repository import MemoryIngestionRepository


class StaticUniverse:
    def latest_memberships(self, **kwargs):  # type: ignore[no-untyped-def]
        return (
            UniverseMembership(
                UUID(int=1), "005930", AssetType.EQUITY, 1, None, 60, False, "liquidity"
            ),
            UniverseMembership(
                UUID(int=2), "069500", AssetType.ETF, 1, None, 60, False, "liquidity"
            ),
        )


class RecordingBatch:
    def __init__(self) -> None:
        self.id = UUID(int=90)
        self.prepared = None
        self.completed = []

    def prepare_job(self, **kwargs):  # type: ignore[no-untyped-def]
        self.prepared = kwargs
        return self.id

    def get_job(self, job_id):  # type: ignore[no-untyped-def]
        return UniverseCollectionJob(
            job_id,
            "sec-edgar-submissions",
            "sec_fundamentals",
            "US",
            date(2026, 8, 21),
            date(2021, 8, 21),
            date(2026, 8, 21),
            75,
            "pending",
        )

    def claim_items(self, **kwargs):  # type: ignore[no-untyped-def]
        return (UniverseCollectionItem(UUID(int=3), "AAPL", "0000320193"),)

    def complete_item(self, **kwargs):  # type: ignore[no-untyped-def]
        self.completed.append(kwargs)

    def fail_item(self, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError(kwargs)

    def refresh_job_status(self, job_id):  # type: ignore[no-untyped-def]
        return None


class StaticCollector:
    def __init__(self, count: int) -> None:
        self.result = tuple(range(count))

    def collect(self, **kwargs):  # type: ignore[no-untyped-def]
        return self.result


def _service(ingestion, batch):  # type: ignore[no-untyped-def]
    return AvailableUniverseCollectionService(
        ingestion_repository=ingestion,
        universe_repository=StaticUniverse(),  # type: ignore[arg-type]
        batch_repository=batch,  # type: ignore[arg-type]
        sec_filings=StaticCollector(2),  # type: ignore[arg-type]
        sec_facts=StaticCollector(3),  # type: ignore[arg-type]
        opendart_filings=StaticCollector(1),  # type: ignore[arg-type]
        opendart_facts=StaticCollector(2),  # type: ignore[arg-type]
        gdelt_news=StaticCollector(4),  # type: ignore[arg-type]
    )


def test_prepare_opendart_uses_corp_code_and_excludes_etf() -> None:
    ingestion = MemoryIngestionRepository()
    ingestion.upsert_assets(
        (
            Asset(UUID(int=1), "삼성전자", AssetType.EQUITY, "KR", "KRW"),
            Asset(UUID(int=2), "KODEX 200", AssetType.ETF, "KR", "KRW"),
        ),
        (AssetIdentifier(UUID(int=1), IdentifierType.DART_CORP_CODE, "00126380"),),
    )
    batch = RecordingBatch()
    job_id = _service(ingestion, batch).prepare(
        job_type="opendart_fundamentals",
        country_code="KR",
        as_of_date=date(2026, 8, 21),
        start_date=date(2021, 8, 21),
        end_date=date(2026, 8, 21),
    )

    assert job_id == UUID(int=90)
    assert [(item.ticker, item.external_identifier) for item in batch.prepared["items"]] == [
        ("005930", "00126380")
    ]


def test_run_sec_item_combines_filing_and_fact_counts() -> None:
    batch = RecordingBatch()
    result = _service(MemoryIngestionRepository(), batch).run(
        job_id=UUID(int=90),
        max_items=1,
        retry_failed=False,
        sec_user_agent="Asset Frame admin@example.com",
    )

    assert result.succeeded == 1
    assert result.records_accepted == 5
    assert batch.completed[0]["records_accepted"] == 5

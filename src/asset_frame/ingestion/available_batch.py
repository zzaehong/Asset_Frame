from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from uuid import UUID

from asset_frame.connectors.gdelt import GDELT_SOURCE_ID
from asset_frame.connectors.opendart import OPENDART_SOURCE_ID
from asset_frame.connectors.sec import SEC_SOURCE_ID
from asset_frame.domain.models import AssetType, IdentifierType
from asset_frame.ingestion.fundamentals_service import (
    OpenDartFinancialFactsCollector,
    SecCompanyFactsCollector,
)
from asset_frame.ingestion.news_service import GdeltNewsCollector
from asset_frame.ingestion.opendart_service import OpenDartDisclosureCollector
from asset_frame.ingestion.retention import years_before
from asset_frame.ingestion.service import SecSubmissionsCollector
from asset_frame.storage.collection_batch import (
    PostgresUniverseCollectionRepository,
    UniverseCollectionItem,
)
from asset_frame.storage.repository import IngestionRepository
from asset_frame.storage.universe import PostgresUniverseRepository

JOB_SOURCE = {
    "sec_fundamentals": (SEC_SOURCE_ID, "US", IdentifierType.CIK),
    "opendart_fundamentals": (
        OPENDART_SOURCE_ID,
        "KR",
        IdentifierType.DART_CORP_CODE,
    ),
    "gdelt_news": (GDELT_SOURCE_ID, None, None),
}


@dataclass(frozen=True, slots=True)
class UniverseCollectionRunResult:
    attempted: int
    succeeded: int
    no_data: int
    failed: int
    records_accepted: int


class AvailableUniverseCollectionService:
    def __init__(
        self,
        *,
        ingestion_repository: IngestionRepository,
        universe_repository: PostgresUniverseRepository,
        batch_repository: PostgresUniverseCollectionRepository,
        sec_filings: SecSubmissionsCollector,
        sec_facts: SecCompanyFactsCollector,
        opendart_filings: OpenDartDisclosureCollector,
        opendart_facts: OpenDartFinancialFactsCollector,
        gdelt_news: GdeltNewsCollector,
    ) -> None:
        self._ingestion_repository = ingestion_repository
        self._universe_repository = universe_repository
        self._batch_repository = batch_repository
        self._sec_filings = sec_filings
        self._sec_facts = sec_facts
        self._opendart_filings = opendart_filings
        self._opendart_facts = opendart_facts
        self._gdelt_news = gdelt_news

    def prepare(
        self,
        *,
        job_type: str,
        country_code: str,
        as_of_date: date,
        start_date: date,
        end_date: date,
        max_news_records: int = 75,
    ) -> UUID:
        if job_type not in JOB_SOURCE:
            raise ValueError("unsupported universe collection job type")
        source_id, required_country, identifier_type = JOB_SOURCE[job_type]
        if required_country is not None and country_code != required_country:
            raise ValueError(f"{job_type} requires country {required_country}")
        if job_type == "gdelt_news" and (end_date - start_date).days > 7:
            raise ValueError("GDELT universe news window must not exceed 7 days")
        if job_type == "gdelt_news" and not 1 <= max_news_records <= 50:
            raise ValueError("GDELT max news records must be between 1 and 50")
        if job_type != "gdelt_news" and start_date < years_before(end_date, 15):
            raise ValueError("fundamentals collection window must not exceed 15 years")
        memberships = self._universe_repository.latest_memberships(
            country_code=country_code, as_of_date=as_of_date
        )
        if not memberships:
            raise RuntimeError("no analysis universe is available for the requested country/date")
        assets = {
            asset.id: asset
            for asset in self._ingestion_repository.list_assets(country_code=country_code)
        }
        identifiers = (
            {
                item.asset_id: item.value
                for item in self._ingestion_repository.list_asset_identifiers(
                    country_code=country_code, identifier_type=identifier_type
                )
            }
            if identifier_type is not None
            else {}
        )
        items = []
        for membership in memberships:
            asset = assets.get(membership.asset_id)
            if asset is None:
                continue
            if job_type == "opendart_fundamentals" and asset.asset_type is AssetType.ETF:
                continue
            query = None
            if job_type == "gdelt_news":
                query_text = (
                    asset.name if asset.name.upper() != membership.ticker else membership.ticker
                )
                query = f'"{query_text.replace(chr(34), "").strip()}"'
            items.append(
                UniverseCollectionItem(
                    asset_id=membership.asset_id,
                    ticker=membership.ticker,
                    external_identifier=identifiers.get(membership.asset_id),
                    search_query=query,
                )
            )
        if not items:
            raise RuntimeError("analysis universe has no applicable collection items")
        return self._batch_repository.prepare_job(
            source_id=source_id,
            job_type=job_type,
            country_code=country_code,
            as_of_date=as_of_date,
            start_date=start_date,
            end_date=end_date,
            max_news_records=max_news_records,
            items=tuple(items),
        )

    def run(
        self,
        *,
        job_id: UUID,
        max_items: int,
        retry_failed: bool,
        sec_user_agent: str | None = None,
        opendart_api_key: str | None = None,
    ) -> UniverseCollectionRunResult:
        if max_items <= 0:
            raise ValueError("max_items must be positive")
        job = self._batch_repository.get_job(job_id)
        expected_source = JOB_SOURCE.get(job.job_type)
        if expected_source is None or job.source_id != expected_source[0]:
            raise ValueError("universe collection job source and type do not match")
        items = self._batch_repository.claim_items(
            job_id=job_id, limit=max_items, retry_failed=retry_failed
        )
        succeeded = no_data = failed = records_accepted = 0
        for item in items:
            try:
                accepted = self._collect_item(
                    job=job,
                    item=item,
                    sec_user_agent=sec_user_agent,
                    opendart_api_key=opendart_api_key,
                )
            except Exception as error:  # noqa: BLE001 - one asset must not abort the batch
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
        return UniverseCollectionRunResult(len(items), succeeded, no_data, failed, records_accepted)

    def _collect_item(
        self,
        *,
        job,  # type: ignore[no-untyped-def]
        item: UniverseCollectionItem,
        sec_user_agent: str | None,
        opendart_api_key: str | None,
    ) -> int:
        if job.job_type == "sec_fundamentals":
            if not item.external_identifier or not sec_user_agent:
                raise RuntimeError("SEC CIK or SEC_USER_AGENT is missing")
            filings = self._sec_filings.collect(
                cik=item.external_identifier,
                asset_id=item.asset_id,
                user_agent=sec_user_agent,
            )
            facts = self._sec_facts.collect(
                cik=item.external_identifier,
                asset_id=item.asset_id,
                user_agent=sec_user_agent,
            )
            return len(filings) + len(facts)
        if job.job_type == "opendart_fundamentals":
            if not item.external_identifier or not opendart_api_key:
                raise RuntimeError("OpenDART corp code or OPENDART_API_KEY is missing")
            filings = self._opendart_filings.collect(
                api_key=opendart_api_key,
                corp_code=item.external_identifier,
                asset_id=item.asset_id,
                start_date=job.start_date,
                end_date=job.end_date,
            )
            accepted = len(filings)
            for business_year in range(job.start_date.year, job.end_date.year + 1):
                accepted += len(
                    self._opendart_facts.collect(
                        api_key=opendart_api_key,
                        corp_code=item.external_identifier,
                        asset_id=item.asset_id,
                        business_year=business_year,
                        report_code="11011",
                        fs_div="CFS",
                    )
                )
            return accepted
        if not item.search_query:
            raise RuntimeError("GDELT search query is missing")
        start_at = datetime.combine(job.start_date, time.min, UTC)
        end_at = datetime.combine(job.end_date, time.max, UTC)
        return len(
            self._gdelt_news.collect(
                asset_id=item.asset_id,
                query=item.search_query,
                start_at=start_at,
                end_at=end_at,
                max_records=job.max_news_records,
            )
        )

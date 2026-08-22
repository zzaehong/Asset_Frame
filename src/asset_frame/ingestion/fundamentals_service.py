from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from asset_frame.connectors.opendart import (
    OPENDART_SOURCE_ID,
    build_financial_facts_request,
    parse_financial_facts,
)
from asset_frame.connectors.sec import (
    SEC_SOURCE_ID,
    build_company_facts_request,
    parse_company_facts,
)
from asset_frame.domain.models import (
    DataKind,
    FinancialFact,
    ImplementationStatus,
    SourceDefinition,
)
from asset_frame.ingestion.financial_policy import (
    FinancialFactPolicy,
    load_financial_fact_policy,
)
from asset_frame.ingestion.run import IngestionRunSession
from asset_frame.ingestion.transport import HttpTransport
from asset_frame.storage.raw import RawStore
from asset_frame.storage.repository import IngestionRepository


class SecCompanyFactsCollector:
    def __init__(
        self,
        *,
        source: SourceDefinition,
        transport: HttpTransport,
        raw_store: RawStore,
        repository: IngestionRepository,
        policy: FinancialFactPolicy | None = None,
    ) -> None:
        _validate_source(source, SEC_SOURCE_ID)
        self._source = source
        self._transport = transport
        self._raw_store = raw_store
        self._repository = repository
        self._policy = policy or load_financial_fact_policy(Path("config/financial-facts.toml"))

    def collect(self, *, cik: str, asset_id: UUID, user_agent: str) -> tuple[FinancialFact, ...]:
        self._repository.upsert_source(self._source)
        with IngestionRunSession(
            self._repository, source_id=self._source.id, data_kind=DataKind.FINANCIAL_FACT.value
        ) as run:
            request = build_company_facts_request(cik, user_agent)
            response = self._transport.fetch(request)
            if response.status_code != 200:
                raise RuntimeError(f"SEC company facts returned HTTP {response.status_code}")
            snapshot = self._raw_store.save(
                snapshot_id=uuid4(),
                source_id=self._source.id,
                request_url=request.url,
                response=response,
                ingestion_run_id=run.id,
            )
            self._repository.save_raw_snapshot(snapshot)
            facts = parse_company_facts(
                response.body,
                asset_id=asset_id,
                snapshot=snapshot,
                expected_cik=cik,
                allowed_concepts=self._policy.sec_concepts,
            )
            self._repository.save_financial_facts(facts)
            run.succeed(records_received=len(facts), records_accepted=len(facts))
            return facts


class OpenDartFinancialFactsCollector:
    def __init__(
        self,
        *,
        source: SourceDefinition,
        transport: HttpTransport,
        raw_store: RawStore,
        repository: IngestionRepository,
        policy: FinancialFactPolicy | None = None,
    ) -> None:
        _validate_source(source, OPENDART_SOURCE_ID)
        self._source = source
        self._transport = transport
        self._raw_store = raw_store
        self._repository = repository
        self._policy = policy or load_financial_fact_policy(Path("config/financial-facts.toml"))

    def collect(
        self,
        *,
        api_key: str,
        corp_code: str,
        asset_id: UUID,
        business_year: int,
        report_code: str,
        fs_div: str,
    ) -> tuple[FinancialFact, ...]:
        self._repository.upsert_source(self._source)
        with IngestionRunSession(
            self._repository, source_id=self._source.id, data_kind=DataKind.FINANCIAL_FACT.value
        ) as run:
            request = build_financial_facts_request(
                api_key=api_key,
                corp_code=corp_code,
                business_year=business_year,
                report_code=report_code,
                fs_div=fs_div,
            )
            response = self._transport.fetch(request)
            if response.status_code != 200:
                raise RuntimeError(f"OpenDART financial facts returned HTTP {response.status_code}")
            snapshot = self._raw_store.save(
                snapshot_id=uuid4(),
                source_id=self._source.id,
                request_url=request.url,
                response=response,
                ingestion_run_id=run.id,
            )
            self._repository.save_raw_snapshot(snapshot)
            facts = parse_financial_facts(
                response.body,
                asset_id=asset_id,
                snapshot=snapshot,
                expected_corp_code=corp_code,
                business_year=business_year,
                report_code=report_code,
                fs_div=fs_div,
                allowed_concepts=self._policy.opendart_concepts,
            )
            self._repository.save_financial_facts(facts)
            run.succeed(records_received=len(facts), records_accepted=len(facts))
            return facts


def _validate_source(source: SourceDefinition, expected_id: str) -> None:
    if source.id != expected_id:
        raise ValueError(f"financial facts collector requires source {expected_id}")
    if not source.enabled or source.implementation_status is not ImplementationStatus.AVAILABLE:
        raise ValueError(f"financial facts source is not available and enabled: {expected_id}")

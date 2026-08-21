from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

from asset_frame.connectors.opendart import (
    OPENDART_SOURCE_ID,
    build_disclosure_request,
    parse_disclosure_page,
)
from asset_frame.domain.models import (
    DataKind,
    FilingDocument,
    ImplementationStatus,
    SourceDefinition,
)
from asset_frame.ingestion.run import IngestionRunSession
from asset_frame.ingestion.transport import HttpTransport
from asset_frame.storage.raw import RawStore
from asset_frame.storage.repository import IngestionRepository


class OpenDartDisclosureCollector:
    def __init__(
        self,
        *,
        source: SourceDefinition,
        transport: HttpTransport,
        raw_store: RawStore,
        repository: IngestionRepository,
    ) -> None:
        if source.id != OPENDART_SOURCE_ID:
            raise ValueError("OpenDART collector requires the OpenDART source definition")
        if not source.enabled or source.implementation_status is not ImplementationStatus.AVAILABLE:
            raise ValueError("OpenDART source is not available and enabled")
        self._source = source
        self._transport = transport
        self._raw_store = raw_store
        self._repository = repository

    def collect(
        self,
        *,
        api_key: str,
        corp_code: str,
        asset_id: UUID,
        start_date: date,
        end_date: date,
    ) -> tuple[FilingDocument, ...]:
        self._repository.upsert_source(self._source)
        with IngestionRunSession(
            self._repository,
            source_id=self._source.id,
            data_kind=DataKind.FILING.value,
        ) as run:
            filings: list[FilingDocument] = []
            page_no = 1
            while True:
                request = build_disclosure_request(
                    api_key=api_key,
                    corp_code=corp_code,
                    start_date=start_date,
                    end_date=end_date,
                    page_no=page_no,
                )
                response = self._transport.fetch(request)
                if response.status_code != 200:
                    raise RuntimeError(f"OpenDART returned HTTP {response.status_code}")
                snapshot = self._raw_store.save(
                    snapshot_id=uuid4(),
                    source_id=self._source.id,
                    request_url=request.url,
                    response=response,
                    ingestion_run_id=run.id,
                )
                self._repository.save_raw_snapshot(snapshot)
                parsed = parse_disclosure_page(
                    response.body,
                    asset_id=asset_id,
                    snapshot=snapshot,
                    expected_corp_code=corp_code,
                )
                if parsed.total_pages > 0 and parsed.page_no != page_no:
                    raise RuntimeError("OpenDART response page number does not match request")
                self._repository.save_filings(parsed.filings)
                filings.extend(parsed.filings)
                if parsed.total_pages == 0 or page_no >= parsed.total_pages:
                    break
                page_no += 1
            run.succeed(records_received=len(filings), records_accepted=len(filings))
            return tuple(filings)

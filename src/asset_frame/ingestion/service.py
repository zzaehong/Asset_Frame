from __future__ import annotations

from uuid import UUID, uuid4

from asset_frame.connectors.sec import (
    SEC_SOURCE_ID,
    build_submissions_request,
    parse_recent_filings,
)
from asset_frame.domain.models import FilingDocument, ImplementationStatus, SourceDefinition
from asset_frame.ingestion.transport import HttpTransport
from asset_frame.storage.raw import RawStore
from asset_frame.storage.repository import IngestionRepository


class IngestionError(RuntimeError):
    pass


class SecSubmissionsCollector:
    def __init__(
        self,
        *,
        source: SourceDefinition,
        transport: HttpTransport,
        raw_store: RawStore,
        repository: IngestionRepository,
    ) -> None:
        if source.id != SEC_SOURCE_ID:
            raise ValueError("SEC collector requires the SEC source definition")
        if not source.enabled or source.implementation_status is not ImplementationStatus.AVAILABLE:
            raise ValueError("SEC source is not available and enabled")
        self._source = source
        self._transport = transport
        self._raw_store = raw_store
        self._repository = repository

    def collect(self, *, cik: str, asset_id: UUID, user_agent: str) -> tuple[FilingDocument, ...]:
        request = build_submissions_request(cik, user_agent)
        response = self._transport.fetch(request)
        if response.status_code != 200:
            raise IngestionError(f"SEC returned HTTP {response.status_code}")

        snapshot = self._raw_store.save(
            snapshot_id=uuid4(),
            source_id=self._source.id,
            request_url=request.url,
            response=response,
        )
        filings = parse_recent_filings(response.body, asset_id=asset_id, snapshot=snapshot)
        self._repository.upsert_source(self._source)
        self._repository.save_raw_snapshot(snapshot)
        self._repository.save_filings(filings)
        return filings

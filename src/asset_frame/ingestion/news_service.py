from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from asset_frame.connectors.gdelt import (
    GDELT_SOURCE_ID,
    build_news_request,
    parse_news,
)
from asset_frame.domain.models import (
    DataKind,
    ImplementationStatus,
    NewsArticleMention,
    SourceDefinition,
)
from asset_frame.ingestion.run import IngestionRunSession
from asset_frame.ingestion.transport import HttpTransport
from asset_frame.storage.raw import RawStore
from asset_frame.storage.repository import IngestionRepository


class GdeltNewsCollector:
    def __init__(
        self,
        *,
        source: SourceDefinition,
        transport: HttpTransport,
        raw_store: RawStore,
        repository: IngestionRepository,
    ) -> None:
        if source.id != GDELT_SOURCE_ID:
            raise ValueError("GDELT collector requires the GDELT DOC source definition")
        if not source.enabled or source.implementation_status is not ImplementationStatus.AVAILABLE:
            raise ValueError("GDELT source is not available and enabled")
        self._source = source
        self._transport = transport
        self._raw_store = raw_store
        self._repository = repository

    def collect(
        self,
        *,
        asset_id: UUID,
        query: str,
        start_at: datetime,
        end_at: datetime,
        max_records: int,
    ) -> tuple[NewsArticleMention, ...]:
        self._repository.upsert_source(self._source)
        with IngestionRunSession(
            self._repository, source_id=self._source.id, data_kind=DataKind.NEWS.value
        ) as run:
            request = build_news_request(
                query=query,
                start_at=start_at,
                end_at=end_at,
                max_records=max_records,
            )
            response = self._transport.fetch(request)
            if response.status_code != 200:
                raise RuntimeError(f"GDELT DOC returned HTTP {response.status_code}")
            snapshot = self._raw_store.save(
                snapshot_id=uuid4(),
                source_id=self._source.id,
                request_url=request.url,
                response=response,
                ingestion_run_id=run.id,
            )
            self._repository.save_raw_snapshot(snapshot)
            mentions = parse_news(
                response.body,
                asset_id=asset_id,
                snapshot=snapshot,
                matched_query=query,
            )
            self._repository.save_news_mentions(mentions)
            run.succeed(records_received=len(mentions), records_accepted=len(mentions))
            return mentions

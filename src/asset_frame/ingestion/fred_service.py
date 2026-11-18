from __future__ import annotations

from uuid import uuid4

from asset_frame.connectors.fred import (
    FRED_SOURCE_ID,
    build_observations_request,
    parse_observations,
)
from asset_frame.domain.models import DataKind, ImplementationStatus, SourceDefinition
from asset_frame.ingestion.run import IngestionRunSession
from asset_frame.ingestion.transport import HttpTransport
from asset_frame.storage.raw import RawStore
from asset_frame.storage.repository import IngestionRepository


class FredCollector:
    def __init__(
        self,
        *,
        source: SourceDefinition,
        transport: HttpTransport,
        raw_store: RawStore,
        repository: IngestionRepository,
    ) -> None:
        if source.id != FRED_SOURCE_ID:
            raise ValueError("FRED collector requires the FRED source definition")
        if not source.enabled or source.implementation_status is not ImplementationStatus.AVAILABLE:
            raise ValueError("FRED source is not available and enabled")
        self._source = source
        self._transport = transport
        self._raw_store = raw_store
        self._repository = repository

    def collect(self, *, series_id: str, api_key: str) -> int:
        self._repository.upsert_source(self._source)
        with IngestionRunSession(
            self._repository, source_id=self._source.id, data_kind=DataKind.MACRO.value
        ) as run:
            request = build_observations_request(series_id, api_key)
            response = self._transport.fetch(request)
            if response.status_code != 200:
                raise RuntimeError(f"FRED returned HTTP {response.status_code}")
            snapshot = self._raw_store.save(
                snapshot_id=uuid4(),
                source_id=self._source.id,
                request_url=request.url,
                response=response,
                ingestion_run_id=run.id,
            )
            self._repository.save_raw_snapshot(snapshot)
            observations = parse_observations(response.body, series_id=series_id, snapshot=snapshot)
            self._repository.save_macro_observations(observations)
            run.succeed(records_received=len(observations), records_accepted=len(observations))
            return len(observations)

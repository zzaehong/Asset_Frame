from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID, uuid4

from asset_frame.connectors.opendart import (
    OPENDART_SOURCE_ID,
    build_corp_code_request,
    parse_corp_code_archive,
)
from asset_frame.connectors.sec import (
    SEC_SOURCE_ID,
    build_ticker_mapping_request,
    parse_ticker_mapping,
)
from asset_frame.domain.models import (
    AssetIdentifier,
    DataKind,
    FetchRequest,
    IdentifierType,
    ImplementationStatus,
    RegulatoryIdentifierRecord,
    SourceDefinition,
)
from asset_frame.ingestion.run import IngestionRunSession
from asset_frame.ingestion.transport import HttpTransport
from asset_frame.storage.raw import RawStore
from asset_frame.storage.repository import IngestionRepository


class IdentifierMappingError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class IdentifierMappingResult:
    records_received: int
    assets_considered: int
    assets_mapped: int
    assets_missing: tuple[str, ...]


class RegulatoryIdentifierCollector:
    def __init__(
        self,
        *,
        source: SourceDefinition,
        country_code: str,
        target_identifier_type: IdentifierType,
        transport: HttpTransport,
        raw_store: RawStore,
        repository: IngestionRepository,
    ) -> None:
        if not source.enabled or source.implementation_status is not ImplementationStatus.AVAILABLE:
            raise ValueError("identifier source is not available and enabled")
        self._source = source
        self._country_code = country_code
        self._target_identifier_type = target_identifier_type
        self._transport = transport
        self._raw_store = raw_store
        self._repository = repository

    def collect_sec(self, *, user_agent: str) -> IdentifierMappingResult:
        if (
            self._source.id != SEC_SOURCE_ID
            or self._target_identifier_type is not IdentifierType.CIK
        ):
            raise ValueError("SEC identifier collector configuration is invalid")
        request = build_ticker_mapping_request(user_agent)
        return self._collect(request, parse_ticker_mapping)

    def collect_opendart(self, *, api_key: str) -> IdentifierMappingResult:
        if (
            self._source.id != OPENDART_SOURCE_ID
            or self._target_identifier_type is not IdentifierType.DART_CORP_CODE
        ):
            raise ValueError("OpenDART identifier collector configuration is invalid")
        request = build_corp_code_request(api_key)
        return self._collect(request, parse_corp_code_archive)

    def _collect(
        self,
        request: FetchRequest,
        parser: Callable[[bytes], tuple[RegulatoryIdentifierRecord, ...]],
    ) -> IdentifierMappingResult:
        self._repository.upsert_source(self._source)
        with IngestionRunSession(
            self._repository,
            source_id=self._source.id,
            data_kind=DataKind.ASSET_IDENTIFIER.value,
        ) as run:
            response = self._transport.fetch(request)
            if response.status_code != 200:
                raise IdentifierMappingError(
                    f"{self._source.id} identifier source returned HTTP {response.status_code}"
                )
            snapshot = self._raw_store.save(
                snapshot_id=uuid4(),
                source_id=self._source.id,
                request_url=request.url,
                response=response,
                ingestion_run_id=run.id,
            )
            self._repository.save_raw_snapshot(snapshot)
            records: tuple[RegulatoryIdentifierRecord, ...] = parser(response.body)
            if any(
                record.identifier_type is not self._target_identifier_type for record in records
            ):
                raise IdentifierMappingError(
                    "identifier parser returned an unexpected identifier type"
                )

            ticker_identifiers = self._repository.list_asset_identifiers(
                country_code=self._country_code,
                identifier_type=IdentifierType.TICKER,
            )
            asset_by_ticker: dict[str, UUID] = {}
            for identifier in ticker_identifiers:
                ticker = identifier.value.strip().upper()
                existing = asset_by_ticker.get(ticker)
                if existing is not None and existing != identifier.asset_id:
                    raise IdentifierMappingError(f"multiple assets share ticker: {ticker}")
                asset_by_ticker[ticker] = identifier.asset_id

            record_by_ticker = {record.ticker.strip().upper(): record for record in records}
            mapped = []
            missing = []
            for ticker, asset_id in asset_by_ticker.items():
                record = record_by_ticker.get(ticker)
                if record is None:
                    missing.append(ticker)
                    continue
                mapped.append(
                    AssetIdentifier(
                        asset_id=asset_id,
                        identifier_type=self._target_identifier_type,
                        value=record.identifier_value,
                    )
                )
            self._repository.save_asset_identifiers(tuple(mapped))
            run.succeed(
                records_received=len(records),
                records_accepted=len(mapped),
            )
            return IdentifierMappingResult(
                records_received=len(records),
                assets_considered=len(asset_by_ticker),
                assets_mapped=len(mapped),
                assets_missing=tuple(sorted(missing)),
            )

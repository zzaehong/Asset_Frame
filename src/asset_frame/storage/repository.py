from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from asset_frame.domain.models import (
    Asset,
    AssetIdentifier,
    CorporateAction,
    IdentifierType,
    MacroObservation,
    PriceObservation,
    QuarantinedPrice,
    RawSnapshot,
    SourceDefinition,
)


class IngestionRepository(Protocol):
    def upsert_source(self, source: SourceDefinition) -> None: ...

    def start_ingestion_run(self, *, source_id: str, data_kind: str) -> UUID: ...

    def complete_ingestion_run(
        self,
        run_id: UUID,
        *,
        records_received: int,
        records_accepted: int,
        records_quarantined: int,
    ) -> None: ...

    def fail_ingestion_run(self, run_id: UUID, *, error_code: str, error_message: str) -> None: ...

    def save_raw_snapshot(self, snapshot: RawSnapshot) -> None: ...

    def upsert_assets(
        self, assets: tuple[Asset, ...], identifiers: tuple[AssetIdentifier, ...]
    ) -> None: ...

    def list_assets(self, *, country_code: str) -> tuple[Asset, ...]: ...

    def list_asset_identifiers(
        self, *, country_code: str, identifier_type: IdentifierType
    ) -> tuple[AssetIdentifier, ...]: ...

    def save_prices(self, prices: tuple[PriceObservation, ...]) -> None: ...

    def save_corporate_actions(self, actions: tuple[CorporateAction, ...]) -> None: ...

    def save_quarantined_prices(self, prices: tuple[QuarantinedPrice, ...]) -> None: ...

    def save_macro_observations(self, observations: tuple[MacroObservation, ...]) -> None: ...


class MemoryIngestionRepository:
    def __init__(self) -> None:
        self.sources: dict[str, SourceDefinition] = {}
        self.ingestion_runs: dict[UUID, dict[str, object]] = {}
        self.snapshots: dict[object, RawSnapshot] = {}
        self.assets: dict[object, Asset] = {}
        self.identifiers: set[AssetIdentifier] = set()
        self.prices: list[PriceObservation] = []
        self.corporate_actions: list[CorporateAction] = []
        self.quarantined_prices: list[QuarantinedPrice] = []
        self.macro_observations: list[MacroObservation] = []

    def upsert_source(self, source: SourceDefinition) -> None:
        self.sources[source.id] = source

    def start_ingestion_run(self, *, source_id: str, data_kind: str) -> UUID:
        run_id = uuid4()
        self.ingestion_runs[run_id] = {
            "source_id": source_id,
            "data_kind": data_kind,
            "status": "started",
            "records_received": 0,
            "records_accepted": 0,
            "records_quarantined": 0,
        }
        return run_id

    def complete_ingestion_run(
        self,
        run_id: UUID,
        *,
        records_received: int,
        records_accepted: int,
        records_quarantined: int,
    ) -> None:
        self.ingestion_runs[run_id].update(
            status="succeeded",
            finished_at=datetime.now(UTC),
            records_received=records_received,
            records_accepted=records_accepted,
            records_quarantined=records_quarantined,
        )

    def fail_ingestion_run(self, run_id: UUID, *, error_code: str, error_message: str) -> None:
        self.ingestion_runs[run_id].update(
            status="failed",
            finished_at=datetime.now(UTC),
            error_code=error_code,
            error_message=error_message,
        )

    def save_raw_snapshot(self, snapshot: RawSnapshot) -> None:
        self.snapshots.setdefault(snapshot.id, snapshot)

    def upsert_assets(
        self, assets: tuple[Asset, ...], identifiers: tuple[AssetIdentifier, ...]
    ) -> None:
        self.assets.update((asset.id, asset) for asset in assets)
        self.identifiers.update(identifiers)

    def list_assets(self, *, country_code: str) -> tuple[Asset, ...]:
        return tuple(asset for asset in self.assets.values() if asset.country_code == country_code)

    def list_asset_identifiers(
        self, *, country_code: str, identifier_type: IdentifierType
    ) -> tuple[AssetIdentifier, ...]:
        asset_ids = {
            asset.id for asset in self.assets.values() if asset.country_code == country_code
        }
        return tuple(
            identifier
            for identifier in self.identifiers
            if identifier.asset_id in asset_ids and identifier.identifier_type is identifier_type
        )

    def save_prices(self, prices: tuple[PriceObservation, ...]) -> None:
        self.prices.extend(prices)

    def save_corporate_actions(self, actions: tuple[CorporateAction, ...]) -> None:
        self.corporate_actions.extend(actions)

    def save_quarantined_prices(self, prices: tuple[QuarantinedPrice, ...]) -> None:
        self.quarantined_prices.extend(prices)

    def save_macro_observations(self, observations: tuple[MacroObservation, ...]) -> None:
        self.macro_observations.extend(observations)

from __future__ import annotations

from typing import Protocol

from asset_frame.domain.models import (
    Asset,
    AssetIdentifier,
    CorporateAction,
    FilingDocument,
    PriceObservation,
    QuarantinedPrice,
    RawSnapshot,
    SourceDefinition,
)


class IngestionRepository(Protocol):
    def upsert_source(self, source: SourceDefinition) -> None: ...

    def save_raw_snapshot(self, snapshot: RawSnapshot) -> None: ...

    def save_filings(self, filings: tuple[FilingDocument, ...]) -> None: ...

    def upsert_assets(
        self, assets: tuple[Asset, ...], identifiers: tuple[AssetIdentifier, ...]
    ) -> None: ...

    def save_prices(self, prices: tuple[PriceObservation, ...]) -> None: ...

    def save_corporate_actions(self, actions: tuple[CorporateAction, ...]) -> None: ...

    def save_quarantined_prices(self, prices: tuple[QuarantinedPrice, ...]) -> None: ...


class MemoryIngestionRepository:
    def __init__(self) -> None:
        self.sources: dict[str, SourceDefinition] = {}
        self.snapshots: dict[object, RawSnapshot] = {}
        self.filings: dict[tuple[str, str], FilingDocument] = {}
        self.assets: dict[object, Asset] = {}
        self.identifiers: set[AssetIdentifier] = set()
        self.prices: list[PriceObservation] = []
        self.corporate_actions: list[CorporateAction] = []
        self.quarantined_prices: list[QuarantinedPrice] = []

    def upsert_source(self, source: SourceDefinition) -> None:
        self.sources[source.id] = source

    def save_raw_snapshot(self, snapshot: RawSnapshot) -> None:
        self.snapshots.setdefault(snapshot.id, snapshot)

    def save_filings(self, filings: tuple[FilingDocument, ...]) -> None:
        for filing in filings:
            self.filings[(filing.source_id, filing.accession_number)] = filing

    def upsert_assets(
        self, assets: tuple[Asset, ...], identifiers: tuple[AssetIdentifier, ...]
    ) -> None:
        self.assets.update((asset.id, asset) for asset in assets)
        self.identifiers.update(identifiers)

    def save_prices(self, prices: tuple[PriceObservation, ...]) -> None:
        self.prices.extend(prices)

    def save_corporate_actions(self, actions: tuple[CorporateAction, ...]) -> None:
        self.corporate_actions.extend(actions)

    def save_quarantined_prices(self, prices: tuple[QuarantinedPrice, ...]) -> None:
        self.quarantined_prices.extend(prices)

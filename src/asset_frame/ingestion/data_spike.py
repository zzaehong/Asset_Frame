from __future__ import annotations

import tomllib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from asset_frame.domain.models import AssetType, IdentifierType
from asset_frame.storage.repository import IngestionRepository


@dataclass(frozen=True, slots=True)
class DataSpikeAsset:
    ticker: str
    country_code: str
    asset_type: AssetType
    coverage_tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DataSpikeReadiness:
    total_assets: int
    assets_registered: int
    required_identifiers_ready: int
    missing_assets: tuple[str, ...]
    missing_required_identifiers: tuple[str, ...]
    asset_type_mismatches: tuple[str, ...]


def load_data_spike_manifest(path: Path) -> tuple[DataSpikeAsset, ...]:
    with path.open("rb") as manifest_file:
        payload = tomllib.load(manifest_file)
    if payload.get("version") != 1:
        raise ValueError("unsupported Data Spike manifest version")
    rows = payload.get("assets")
    if not isinstance(rows, list):
        raise ValueError("Data Spike manifest assets must be a list")

    assets = tuple(_parse_asset(row) for row in rows)
    if len(assets) != 20:
        raise ValueError("Data Spike manifest must contain exactly 20 assets")
    keys = [(asset.country_code, asset.ticker) for asset in assets]
    if len(keys) != len(set(keys)):
        raise ValueError("Data Spike manifest contains duplicate country/ticker pairs")
    groups = Counter((asset.country_code, asset.asset_type) for asset in assets)
    expected = {
        ("KR", AssetType.EQUITY): 5,
        ("KR", AssetType.ETF): 5,
        ("US", AssetType.EQUITY): 5,
        ("US", AssetType.ETF): 5,
    }
    if groups != expected:
        raise ValueError("Data Spike manifest requires five assets in each market/type group")
    return assets


def evaluate_data_spike_readiness(
    repository: IngestionRepository, manifest: tuple[DataSpikeAsset, ...]
) -> DataSpikeReadiness:
    registered: set[tuple[str, str]] = set()
    required_identifiers_ready: set[tuple[str, str]] = set()
    type_mismatches: set[tuple[str, str]] = set()
    manifest_by_key = {(asset.country_code, asset.ticker): asset for asset in manifest}
    for country_code in ("KR", "US"):
        tickers_by_asset = _current_identifiers_by_asset(
            repository, country_code=country_code, identifier_type=IdentifierType.TICKER
        )
        cik_by_asset = _current_identifiers_by_asset(
            repository, country_code=country_code, identifier_type=IdentifierType.CIK
        )
        dart_by_asset = _current_identifiers_by_asset(
            repository,
            country_code=country_code,
            identifier_type=IdentifierType.DART_CORP_CODE,
        )
        assets_by_id = {
            asset.id: asset for asset in repository.list_assets(country_code=country_code)
        }
        asset_by_ticker: dict[str, UUID] = {}
        for asset_id, ticker in tickers_by_asset.items():
            key = (country_code, ticker)
            existing = asset_by_ticker.get(ticker)
            if existing is not None and existing != asset_id:
                raise ValueError(
                    f"multiple assets share Data Spike ticker: {country_code}:{ticker}"
                )
            asset_by_ticker[ticker] = asset_id
            expected = manifest_by_key.get(key)
            if expected is None:
                continue
            stored_asset = assets_by_id.get(asset_id)
            if stored_asset is None or stored_asset.asset_type is not expected.asset_type:
                type_mismatches.add(key)
                continue
            registered.add(key)
            identifier_ready = (country_code == "US" and asset_id in cik_by_asset) or (
                country_code == "KR"
                and (expected.asset_type is AssetType.ETF or asset_id in dart_by_asset)
            )
            if identifier_ready:
                required_identifiers_ready.add(key)

    manifest_keys = set(manifest_by_key)
    missing_assets = manifest_keys - registered - type_mismatches
    missing_required = manifest_keys - required_identifiers_ready - missing_assets - type_mismatches
    return DataSpikeReadiness(
        total_assets=len(manifest),
        assets_registered=len(manifest_keys & registered),
        required_identifiers_ready=len(manifest_keys & required_identifiers_ready),
        missing_assets=tuple(_format_keys(missing_assets)),
        missing_required_identifiers=tuple(_format_keys(missing_required)),
        asset_type_mismatches=tuple(_format_keys(type_mismatches)),
    )


def _parse_asset(row: object) -> DataSpikeAsset:
    if not isinstance(row, dict):
        raise ValueError("Data Spike asset must be a table")
    ticker = row.get("ticker")
    country_code = row.get("country_code")
    tags = row.get("coverage_tags")
    if not isinstance(ticker, str) or not ticker or ticker != ticker.strip().upper():
        raise ValueError("Data Spike ticker must be non-empty uppercase text")
    if country_code not in ("KR", "US"):
        raise ValueError("Data Spike country_code must be KR or US")
    if not isinstance(tags, list) or not tags or not all(isinstance(tag, str) for tag in tags):
        raise ValueError("Data Spike coverage_tags must be a non-empty string list")
    try:
        asset_type = AssetType(row.get("asset_type"))
    except ValueError as error:
        raise ValueError("Data Spike asset_type must be equity or etf") from error
    return DataSpikeAsset(ticker, country_code, asset_type, tuple(tags))


def _current_identifiers_by_asset(
    repository: IngestionRepository,
    *,
    country_code: str,
    identifier_type: IdentifierType,
) -> dict[UUID, str]:
    return {
        identifier.asset_id: identifier.value.strip().upper()
        for identifier in repository.list_asset_identifiers(
            country_code=country_code, identifier_type=identifier_type
        )
    }


def _format_keys(keys: set[tuple[str, str]]) -> list[str]:
    return [f"{country}:{ticker}" for country, ticker in sorted(keys)]

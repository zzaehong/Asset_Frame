from pathlib import Path
from uuid import uuid4

import pytest

from asset_frame.domain.models import Asset, AssetIdentifier, AssetType, IdentifierType
from asset_frame.ingestion.data_spike import (
    evaluate_data_spike_readiness,
    load_data_spike_manifest,
)
from asset_frame.storage.repository import MemoryIngestionRepository


def test_data_spike_manifest_has_required_groups_and_edge_coverage() -> None:
    manifest = load_data_spike_manifest(Path("config/data-spike.toml"))

    assert len(manifest) == 20
    tags = {tag for asset in manifest for tag in asset.coverage_tags}
    assert {"historical_split", "cash_dividend", "nonstandard_ticker", "inverse"} <= tags
    assert {"bond", "commodity", "foreign_underlying"} <= tags


def test_data_spike_readiness_separates_missing_asset_and_identifier() -> None:
    manifest = load_data_spike_manifest(Path("config/data-spike.toml"))
    repository = MemoryIngestionRepository()
    apple = Asset(
        id=uuid4(),
        name="Apple Inc.",
        asset_type=AssetType.EQUITY,
        country_code="US",
        currency="USD",
    )
    microsoft = Asset(
        id=uuid4(),
        name="Microsoft Corporation",
        asset_type=AssetType.EQUITY,
        country_code="US",
        currency="USD",
    )
    unrelated = Asset(uuid4(), "Unrelated", AssetType.EQUITY, "US", "USD")
    repository.upsert_assets(
        (apple, microsoft, unrelated),
        (
            AssetIdentifier(apple.id, IdentifierType.TICKER, "AAPL"),
            AssetIdentifier(apple.id, IdentifierType.CIK, "0000320193"),
            AssetIdentifier(microsoft.id, IdentifierType.TICKER, "MSFT"),
            AssetIdentifier(unrelated.id, IdentifierType.TICKER, "NOT-IN-MANIFEST"),
        ),
    )

    readiness = evaluate_data_spike_readiness(repository, manifest)

    assert readiness.total_assets == 20
    assert readiness.assets_registered == 2
    assert readiness.required_identifiers_ready == 1
    assert "US:MSFT" in readiness.missing_required_identifiers
    assert "KR:005930" in readiness.missing_assets
    assert readiness.asset_type_mismatches == ()


def test_data_spike_readiness_rejects_registered_asset_type_mismatch() -> None:
    manifest = load_data_spike_manifest(Path("config/data-spike.toml"))
    repository = MemoryIngestionRepository()
    apple = Asset(uuid4(), "Apple Inc.", AssetType.ETF, "US", "USD")
    repository.upsert_assets(
        (apple,),
        (
            AssetIdentifier(apple.id, IdentifierType.TICKER, "AAPL"),
            AssetIdentifier(apple.id, IdentifierType.CIK, "0000320193"),
        ),
    )

    readiness = evaluate_data_spike_readiness(repository, manifest)

    assert readiness.assets_registered == 0
    assert readiness.required_identifiers_ready == 0
    assert readiness.asset_type_mismatches == ("US:AAPL",)


def test_korean_etf_does_not_require_inapplicable_dart_corp_code() -> None:
    manifest = load_data_spike_manifest(Path("config/data-spike.toml"))
    repository = MemoryIngestionRepository()
    etf = Asset(uuid4(), "Korean ETF", AssetType.ETF, "KR", "KRW")
    repository.upsert_assets(
        (etf,),
        (AssetIdentifier(etf.id, IdentifierType.TICKER, "069500"),),
    )

    readiness = evaluate_data_spike_readiness(repository, manifest)

    assert readiness.assets_registered == 1
    assert readiness.required_identifiers_ready == 1
    assert "KR:069500" not in readiness.missing_required_identifiers


def test_data_spike_manifest_rejects_wrong_size(tmp_path: Path) -> None:
    manifest = tmp_path / "data-spike.toml"
    manifest.write_text("version = 1\nassets = []\n", encoding="utf-8")

    with pytest.raises(ValueError, match="exactly 20"):
        load_data_spike_manifest(manifest)

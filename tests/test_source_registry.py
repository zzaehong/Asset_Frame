from pathlib import Path

import pytest

from asset_frame.domain.models import AccessMethod, DataKind, ImplementationStatus
from asset_frame.sources.registry import SourcePolicyError, load_source_registry


def test_project_registry_contains_only_official_access_methods() -> None:
    sources = load_source_registry(Path("config/sources.toml"))

    assert sources
    assert all(source.access_method in AccessMethod for source in sources)
    assert all(
        not source.enabled or source.implementation_status is ImplementationStatus.AVAILABLE
        for source in sources
    )


def test_available_collectors_declare_their_ingested_data_kinds() -> None:
    sources = {source.id: source for source in load_source_registry(Path("config/sources.toml"))}
    expected = {
        "sec-edgar-submissions": {
            DataKind.ASSET_IDENTIFIER,
            DataKind.FILING,
            DataKind.FINANCIAL_FACT,
        },
        "krx-open-api": {DataKind.ASSET_IDENTIFIER, DataKind.PRICE},
        "opendart": {
            DataKind.ASSET_IDENTIFIER,
            DataKind.FILING,
            DataKind.FINANCIAL_FACT,
        },
        "tiingo-eod": {DataKind.PRICE, DataKind.CORPORATE_ACTION},
        "gdelt-doc": {DataKind.NEWS},
    }

    for source_id, required_data_kinds in expected.items():
        assert required_data_kinds <= set(sources[source_id].data_kinds)


def test_registry_rejects_scraping(tmp_path: Path) -> None:
    registry = tmp_path / "sources.toml"
    registry.write_text(
        """
schema_version = 1
[[sources]]
id = "bad"
authority = "Unofficial"
authority_type = "documented_provider"
access_method = "scraping"
role = "primary"
data_kinds = ["price"]
documentation_url = "https://example.com/docs"
terms_url = "https://example.com/terms"
verification_url = "https://example.com"
enabled = true
implementation_status = "available"
"""
    )

    with pytest.raises(SourcePolicyError):
        load_source_registry(registry)


def test_registry_rejects_unrecognized_authority_type(tmp_path: Path) -> None:
    registry = tmp_path / "sources.toml"
    registry.write_text(
        """
schema_version = 1
[[sources]]
id = "bad"
authority = "Unknown"
authority_type = "unofficial"
access_method = "official_api"
role = "primary"
data_kinds = ["price"]
documentation_url = "https://example.com/docs"
terms_url = "https://example.com/terms"
verification_url = "https://example.com"
enabled = true
implementation_status = "available"
"""
    )

    with pytest.raises(SourcePolicyError):
        load_source_registry(registry)

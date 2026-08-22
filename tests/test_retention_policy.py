from datetime import date
from pathlib import Path
from uuid import UUID

import pytest

from asset_frame.ingestion.retention import load_retention_policy, years_before
from asset_frame.storage.retention import PrunedRawSnapshot, delete_pruned_raw_files


def test_repository_retention_contract_is_strict_and_uniform() -> None:
    policy = load_retention_policy(Path("config/retention-policy.toml"))

    assert policy.news_lookback_days == 7
    assert policy.news_max_articles_per_asset == 50
    assert policy.news_max_records_per_request == 50
    assert policy.filing_lookback_years == 15
    assert policy.price_lookback_years == 10
    assert policy.price_max_observations_per_asset_source == 2600
    assert policy.require_complete_ohlc is True


def test_years_before_handles_leap_day() -> None:
    assert years_before(date(2024, 2, 29), 10) == date(2014, 2, 28)


def test_retention_policy_rejects_incomplete_ohlc(tmp_path: Path) -> None:
    path = tmp_path / "retention.toml"
    path.write_text(
        Path("config/retention-policy.toml")
        .read_text(encoding="utf-8")
        .replace("require_complete_ohlc = true", "require_complete_ohlc = false"),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="complete OHLC"):
        load_retention_policy(path)


def test_pruned_raw_file_cleanup_removes_only_selected_snapshot(tmp_path: Path) -> None:
    snapshot_id = UUID(int=1)
    metadata = tmp_path / "gdelt-doc" / "snapshots" / f"{snapshot_id}.json"
    body = tmp_path / "gdelt-doc" / "aa" / "payload.bin"
    metadata.parent.mkdir(parents=True)
    body.parent.mkdir(parents=True)
    metadata.write_text("metadata", encoding="utf-8")
    body.write_bytes(b"payload")

    removed = delete_pruned_raw_files(
        tmp_path,
        (PrunedRawSnapshot(snapshot_id, "gdelt-doc/aa/payload.bin", True),),
    )

    assert removed == 2
    assert not metadata.exists()
    assert not body.exists()

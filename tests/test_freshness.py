from datetime import UTC, datetime, timedelta

import pytest

from asset_frame.ingestion.freshness import evaluate_freshness
from asset_frame.ingestion.run import IngestionRunSession
from asset_frame.storage.repository import MemoryIngestionRepository


def test_freshness_reports_missing_recent_and_stale_runs() -> None:
    as_of = datetime(2026, 8, 21, 12, tzinfo=UTC)

    missing = evaluate_freshness(last_success_at=None, as_of=as_of, max_age=timedelta(hours=24))
    recent = evaluate_freshness(
        last_success_at=as_of - timedelta(hours=23),
        as_of=as_of,
        max_age=timedelta(hours=24),
    )
    stale = evaluate_freshness(
        last_success_at=as_of - timedelta(hours=25),
        as_of=as_of,
        max_age=timedelta(hours=24),
    )

    assert missing.stale is True
    assert missing.reason == "no_successful_run"
    assert recent.stale is False
    assert recent.reason == "within_max_age"
    assert stale.stale is True
    assert stale.reason == "older_than_max_age"


def test_freshness_requires_explicit_valid_time_contract() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate_freshness(
            last_success_at=None,
            as_of=datetime(2026, 8, 21),
            max_age=timedelta(hours=24),
        )
    with pytest.raises(ValueError, match="positive"):
        evaluate_freshness(
            last_success_at=None,
            as_of=datetime(2026, 8, 21, tzinfo=UTC),
            max_age=timedelta(0),
        )


def test_ingestion_run_rejects_impossible_counts_and_records_failure() -> None:
    repository = MemoryIngestionRepository()

    with (
        pytest.raises(ValueError, match="cannot exceed"),
        IngestionRunSession(repository, source_id="official-source", data_kind="price") as run,
    ):
        run.succeed(records_received=1, records_accepted=1, records_quarantined=1)

    stored = next(iter(repository.ingestion_runs.values()))
    assert stored["status"] == "failed"
    assert stored["error_code"] == "ValueError"

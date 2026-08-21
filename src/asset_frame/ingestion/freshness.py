from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True, slots=True)
class FreshnessStatus:
    last_success_at: datetime | None
    stale: bool
    reason: str


def evaluate_freshness(
    *, last_success_at: datetime | None, as_of: datetime, max_age: timedelta
) -> FreshnessStatus:
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    if max_age <= timedelta(0):
        raise ValueError("max_age must be positive")
    if last_success_at is None:
        return FreshnessStatus(None, True, "no_successful_run")
    if last_success_at.tzinfo is None:
        raise ValueError("last_success_at must be timezone-aware")
    stale = as_of - last_success_at > max_age
    return FreshnessStatus(
        last_success_at,
        stale,
        "older_than_max_age" if stale else "within_max_age",
    )

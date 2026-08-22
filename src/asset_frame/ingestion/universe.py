from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from asset_frame.domain.models import AssetType


@dataclass(frozen=True, slots=True)
class UniversePolicy:
    equity_limit: int
    etf_limit: int
    lookback_observations: int
    minimum_observations: int
    storage_warning_gb: Decimal


@dataclass(frozen=True, slots=True)
class LiquidityCandidate:
    asset_id: UUID
    ticker: str
    asset_type: AssetType
    median_dollar_volume: Decimal | None
    observation_count: int
    pinned: bool = False


@dataclass(frozen=True, slots=True)
class UniverseMembership:
    asset_id: UUID
    ticker: str
    asset_type: AssetType
    selected_rank: int
    median_dollar_volume: Decimal | None
    observation_count: int
    pinned: bool
    selection_reason: str


@dataclass(frozen=True, slots=True)
class UniverseSelection:
    country_code: str
    as_of_date: date
    memberships: tuple[UniverseMembership, ...]
    input_hash: str


def load_universe_policy(path: Path) -> UniversePolicy:
    with path.open("rb") as file:
        payload = tomllib.load(file)
    policy = payload.get("policy")
    if not isinstance(policy, dict):
        raise ValueError("analysis universe config requires a [policy] table")
    result = UniversePolicy(
        equity_limit=_positive_int(policy, "equity_limit"),
        etf_limit=_positive_int(policy, "etf_limit"),
        lookback_observations=_positive_int(policy, "lookback_observations"),
        minimum_observations=_positive_int(policy, "minimum_observations"),
        storage_warning_gb=Decimal(str(policy.get("storage_warning_gb", "10"))),
    )
    if result.minimum_observations > result.lookback_observations:
        raise ValueError("minimum_observations cannot exceed lookback_observations")
    if result.storage_warning_gb <= 0:
        raise ValueError("storage_warning_gb must be positive")
    return result


def select_analysis_universe(
    *,
    country_code: str,
    as_of_date: date,
    candidates: tuple[LiquidityCandidate, ...],
    policy: UniversePolicy,
) -> UniverseSelection:
    normalized_country = country_code.upper()
    if normalized_country not in {"KR", "US"}:
        raise ValueError("country_code must be KR or US")
    _validate_unique_candidates(candidates)

    memberships: list[UniverseMembership] = []
    for asset_type, limit in (
        (AssetType.EQUITY, policy.equity_limit),
        (AssetType.ETF, policy.etf_limit),
    ):
        typed = [candidate for candidate in candidates if candidate.asset_type is asset_type]
        eligible = [
            candidate
            for candidate in typed
            if candidate.pinned
            or (
                candidate.observation_count >= policy.minimum_observations
                and candidate.median_dollar_volume is not None
                and candidate.median_dollar_volume >= 0
            )
        ]
        ranked = sorted(
            eligible,
            key=lambda item: (
                not item.pinned,
                -(item.median_dollar_volume or Decimal(0)),
                item.ticker.upper(),
            ),
        )[:limit]
        memberships.extend(
            UniverseMembership(
                asset_id=candidate.asset_id,
                ticker=candidate.ticker.upper(),
                asset_type=candidate.asset_type,
                selected_rank=rank,
                median_dollar_volume=candidate.median_dollar_volume,
                observation_count=candidate.observation_count,
                pinned=candidate.pinned,
                selection_reason=(
                    "data_spike_pinned" if candidate.pinned else "median_dollar_volume"
                ),
            )
            for rank, candidate in enumerate(ranked, start=1)
        )

    ordered = tuple(
        sorted(memberships, key=lambda item: (item.asset_type.value, item.selected_rank))
    )
    return UniverseSelection(
        country_code=normalized_country,
        as_of_date=as_of_date,
        memberships=ordered,
        input_hash=_selection_hash(normalized_country, as_of_date, candidates, policy),
    )


def _positive_int(payload: dict[str, object], name: str) -> int:
    value = payload.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _validate_unique_candidates(candidates: tuple[LiquidityCandidate, ...]) -> None:
    asset_ids = [candidate.asset_id for candidate in candidates]
    tickers = [candidate.ticker.upper() for candidate in candidates]
    if len(asset_ids) != len(set(asset_ids)):
        raise ValueError("candidate asset_id values must be unique")
    if len(tickers) != len(set(tickers)):
        raise ValueError("candidate tickers must be unique")


def _selection_hash(
    country_code: str,
    as_of_date: date,
    candidates: tuple[LiquidityCandidate, ...],
    policy: UniversePolicy,
) -> str:
    payload = {
        "country_code": country_code,
        "as_of_date": as_of_date.isoformat(),
        "policy": {
            "equity_limit": policy.equity_limit,
            "etf_limit": policy.etf_limit,
            "lookback_observations": policy.lookback_observations,
            "minimum_observations": policy.minimum_observations,
        },
        "candidates": [
            {
                "asset_id": str(item.asset_id),
                "ticker": item.ticker.upper(),
                "asset_type": item.asset_type.value,
                "median_dollar_volume": (
                    str(item.median_dollar_volume)
                    if item.median_dollar_volume is not None
                    else None
                ),
                "observation_count": item.observation_count,
                "pinned": item.pinned,
            }
            for item in sorted(candidates, key=lambda candidate: str(candidate.asset_id))
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()

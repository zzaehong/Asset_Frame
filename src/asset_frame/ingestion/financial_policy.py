from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class FinancialFactPolicy:
    id: str
    sec_concepts: frozenset[str]
    opendart_concepts: frozenset[str]


def load_financial_fact_policy(path: Path) -> FinancialFactPolicy:
    with path.open("rb") as file:
        payload = tomllib.load(file)
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported financial fact policy schema version")
    policy_id = payload.get("policy_id")
    if not isinstance(policy_id, str) or not policy_id:
        raise ValueError("financial fact policy id is required")
    return FinancialFactPolicy(
        id=policy_id,
        sec_concepts=_strings(payload, "sec_concepts"),
        opendart_concepts=_strings(payload, "opendart_concepts"),
    )


def _strings(payload: dict[str, object], name: str) -> frozenset[str]:
    values = payload.get(name)
    if (
        not isinstance(values, list)
        or not values
        or any(not isinstance(value, str) or not value for value in values)
    ):
        raise ValueError(f"financial fact policy list is invalid: {name}")
    if len(set(values)) != len(values):
        raise ValueError(f"financial fact policy list contains duplicates: {name}")
    return frozenset(values)

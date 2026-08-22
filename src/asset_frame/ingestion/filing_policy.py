from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

from asset_frame.connectors.opendart import OPENDART_SOURCE_ID
from asset_frame.connectors.sec import SEC_SOURCE_ID
from asset_frame.domain.models import FilingDocument

_DART_PREFIX = re.compile(r"^\s*\[[^]]+정정]\s*")


@dataclass(frozen=True, slots=True)
class FilingSelectionPolicy:
    id: str
    sec_categories: tuple[tuple[str, frozenset[str]], ...]
    opendart_categories: tuple[tuple[str, tuple[str, ...]], ...]


def load_filing_policy(path: Path) -> FilingSelectionPolicy:
    with path.open("rb") as file:
        payload = tomllib.load(file)
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported filing policy schema version")
    policy_id = payload.get("policy_id")
    if not isinstance(policy_id, str) or not policy_id:
        raise ValueError("filing policy id is required")
    sec = _category_table(payload, "sec")
    opendart = _category_table(payload, "opendart")
    return FilingSelectionPolicy(
        id=policy_id,
        sec_categories=tuple((category, frozenset(values)) for category, values in sec),
        opendart_categories=tuple((category, values) for category, values in opendart),
    )


def select_major_filings(
    filings: tuple[FilingDocument, ...], policy: FilingSelectionPolicy
) -> tuple[FilingDocument, ...]:
    selected = []
    for filing in filings:
        category = _category(filing, policy)
        if category is None:
            continue
        selected.append(
            replace(
                filing,
                metadata={
                    **filing.metadata,
                    "selection_policy": policy.id,
                    "selection_category": category,
                },
            )
        )
    return tuple(selected)


def _category(filing: FilingDocument, policy: FilingSelectionPolicy) -> str | None:
    if filing.source_id == SEC_SOURCE_ID:
        normalized = filing.form_type.strip().upper()
        for category, forms in policy.sec_categories:
            if normalized in forms:
                return category
        return None
    if filing.source_id == OPENDART_SOURCE_ID:
        normalized = _DART_PREFIX.sub("", filing.form_type).strip()
        for category, prefixes in policy.opendart_categories:
            if any(normalized.startswith(prefix) for prefix in prefixes):
                return category
        return None
    raise ValueError(f"filing selection policy does not support source: {filing.source_id}")


def _category_table(
    payload: dict[str, object], name: str
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    table = payload.get(name)
    if not isinstance(table, dict) or not table:
        raise ValueError(f"filing policy section is required: {name}")
    categories = []
    seen: set[str] = set()
    for category, raw_values in table.items():
        if not isinstance(category, str) or not isinstance(raw_values, list) or not raw_values:
            raise ValueError(f"filing policy category is invalid: {name}.{category}")
        values = tuple(
            value.strip().upper() if name == "sec" else value.strip()
            for value in raw_values
            if isinstance(value, str) and value.strip()
        )
        if len(values) != len(raw_values):
            raise ValueError(f"filing policy values are invalid: {name}.{category}")
        duplicates = seen.intersection(values)
        if duplicates:
            raise ValueError(f"filing policy values are duplicated: {sorted(duplicates)}")
        seen.update(values)
        categories.append((category, values))
    return tuple(categories)

from __future__ import annotations

import tomllib
from pathlib import Path
from urllib.parse import urlparse

from asset_frame.domain.models import (
    AccessMethod,
    AuthorityType,
    DataKind,
    ImplementationStatus,
    SourceDefinition,
    SourceRole,
)


class SourcePolicyError(ValueError):
    """Raised when a source violates the official-source policy."""


_ALLOWED_SCHEMES = {"https"}


def load_source_registry(path: Path) -> tuple[SourceDefinition, ...]:
    with path.open("rb") as registry_file:
        payload = tomllib.load(registry_file)

    if payload.get("schema_version") != 1:
        raise SourcePolicyError("unsupported source registry schema version")

    sources = tuple(_parse_source(item) for item in payload.get("sources", []))
    ids = [source.id for source in sources]
    if len(ids) != len(set(ids)):
        raise SourcePolicyError("source ids must be unique")
    if not sources:
        raise SourcePolicyError("source registry must not be empty")
    return sources


def _parse_source(item: dict[str, object]) -> SourceDefinition:
    try:
        source = SourceDefinition(
            id=str(item["id"]),
            authority=str(item["authority"]),
            authority_type=AuthorityType(str(item["authority_type"])),
            access_method=AccessMethod(str(item["access_method"])),
            role=SourceRole(str(item["role"])),
            data_kinds=tuple(DataKind(str(kind)) for kind in item["data_kinds"]),  # type: ignore[union-attr]
            documentation_url=str(item["documentation_url"]),
            terms_url=str(item["terms_url"]),
            verification_url=str(item["verification_url"]),
            enabled=bool(item["enabled"]),
            implementation_status=ImplementationStatus(str(item["implementation_status"])),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise SourcePolicyError(f"invalid source definition: {error}") from error

    if not source.id or not source.authority or not source.data_kinds:
        raise SourcePolicyError("source id, authority, and data kinds are required")
    for url in (source.documentation_url, source.terms_url, source.verification_url):
        parsed = urlparse(url)
        if parsed.scheme not in _ALLOWED_SCHEMES or not parsed.netloc:
            raise SourcePolicyError(f"source URLs must be absolute HTTPS URLs: {url}")
    if source.enabled and source.implementation_status is not ImplementationStatus.AVAILABLE:
        raise SourcePolicyError("only available sources can be enabled")
    return source

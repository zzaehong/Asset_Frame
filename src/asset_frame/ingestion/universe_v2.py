from __future__ import annotations

import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from uuid import UUID

from asset_frame.domain.models import AssetType


class UniverseKind(StrEnum):
    CORE_ETF = "core_etf"
    INVESTOR_EQUITY = "investor_equity"
    KRX_INDEX_EQUITY = "krx_index_equity"


class MembershipStatus(StrEnum):
    ACTIVE = "active"
    COOLING = "cooling"
    ARCHIVED = "archived"


class UniverseEvidenceType(StrEnum):
    ETF_CATALOG = "etf_catalog"
    SEC_13F = "sec_13f"
    KRX_KOSPI_200 = "krx_kospi_200"
    KRX_KOSDAQ_150 = "krx_kosdaq_150"


@dataclass(frozen=True, slots=True)
class UniverseV2Policy:
    policy_version: int
    etf_limit: int
    investor_equity_limit: int
    tiingo_monthly_unique_symbol_limit: int
    cooling_quarters: int
    allowed_countries: frozenset[str]
    krx_equity_evidence: frozenset[UniverseEvidenceType]
    allow_duplicate_exposures: bool


@dataclass(frozen=True, slots=True)
class EvidenceUniverseMember:
    asset_id: UUID
    country_code: str
    exchange_code: str
    ticker: str
    asset_type: AssetType
    universe_kind: UniverseKind
    evidence_types: frozenset[UniverseEvidenceType]
    status: MembershipStatus = MembershipStatus.ACTIVE
    exposure_key: str | None = None
    price_source_id: str | None = None


@dataclass(frozen=True, slots=True)
class UniverseCompositionSummary:
    active_etfs: int
    active_investor_equities: int
    active_krx_index_equities: int
    tiingo_monthly_unique_symbols: int


def load_universe_v2_policy(path: Path) -> UniverseV2Policy:
    with path.open("rb") as file:
        payload = tomllib.load(file)
    policy = payload.get("universe_v2")
    if not isinstance(policy, dict):
        raise ValueError("analysis universe config requires a [universe_v2] table")

    allowed_countries = _string_set(policy, "allowed_countries")
    normalized_countries = frozenset(country.upper() for country in allowed_countries)
    if not normalized_countries or not normalized_countries <= {"KR", "US"}:
        raise ValueError("allowed_countries must contain only KR or US")

    evidence_names = _string_set(policy, "krx_equity_evidence")
    try:
        krx_evidence = frozenset(UniverseEvidenceType(name) for name in evidence_names)
    except ValueError as error:
        raise ValueError("krx_equity_evidence contains an unsupported value") from error
    supported_krx_evidence = {
        UniverseEvidenceType.KRX_KOSPI_200,
        UniverseEvidenceType.KRX_KOSDAQ_150,
    }
    if not krx_evidence or not krx_evidence <= supported_krx_evidence:
        raise ValueError("krx_equity_evidence must contain KOSPI 200 or KOSDAQ 150")

    duplicate_exposures = policy.get("allow_duplicate_exposures")
    if not isinstance(duplicate_exposures, bool):
        raise ValueError("allow_duplicate_exposures must be a boolean")

    return UniverseV2Policy(
        policy_version=_positive_int(policy, "policy_version"),
        etf_limit=_positive_int(policy, "etf_limit"),
        investor_equity_limit=_positive_int(policy, "investor_equity_limit"),
        tiingo_monthly_unique_symbol_limit=_positive_int(
            policy, "tiingo_monthly_unique_symbol_limit"
        ),
        cooling_quarters=_positive_int(policy, "cooling_quarters"),
        allowed_countries=normalized_countries,
        krx_equity_evidence=krx_evidence,
        allow_duplicate_exposures=duplicate_exposures,
    )


def validate_universe_composition(
    members: tuple[EvidenceUniverseMember, ...], policy: UniverseV2Policy
) -> UniverseCompositionSummary:
    _validate_unique_members(members)
    for member in members:
        _validate_member(member, policy)

    active = tuple(member for member in members if member.status is MembershipStatus.ACTIVE)
    active_etfs = sum(member.universe_kind is UniverseKind.CORE_ETF for member in active)
    active_investor_equities = sum(
        member.universe_kind is UniverseKind.INVESTOR_EQUITY for member in active
    )
    active_krx_index_equities = sum(
        member.universe_kind is UniverseKind.KRX_INDEX_EQUITY for member in active
    )
    if active_etfs > policy.etf_limit:
        raise ValueError(f"active ETF count exceeds policy limit {policy.etf_limit}")
    if active_investor_equities > policy.investor_equity_limit:
        raise ValueError(
            f"active investor equity count exceeds policy limit {policy.investor_equity_limit}"
        )

    tiingo_symbols = {
        member.ticker.upper()
        for member in members
        if member.status is not MembershipStatus.ARCHIVED and member.price_source_id == "tiingo-eod"
    }
    if len(tiingo_symbols) > policy.tiingo_monthly_unique_symbol_limit:
        raise ValueError(
            "Tiingo unique symbol count exceeds policy limit "
            f"{policy.tiingo_monthly_unique_symbol_limit}"
        )

    if not policy.allow_duplicate_exposures:
        exposure_keys = [
            member.exposure_key
            for member in active
            if member.universe_kind is UniverseKind.CORE_ETF
        ]
        if len(exposure_keys) != len(set(exposure_keys)):
            raise ValueError("duplicate ETF exposures are disabled by policy")

    return UniverseCompositionSummary(
        active_etfs=active_etfs,
        active_investor_equities=active_investor_equities,
        active_krx_index_equities=active_krx_index_equities,
        tiingo_monthly_unique_symbols=len(tiingo_symbols),
    )


def _validate_unique_members(members: tuple[EvidenceUniverseMember, ...]) -> None:
    asset_ids = [member.asset_id for member in members]
    if len(asset_ids) != len(set(asset_ids)):
        raise ValueError("universe asset_id values must be unique")
    listing_keys = [
        (member.country_code.upper(), member.exchange_code.upper(), member.ticker.upper())
        for member in members
    ]
    if len(listing_keys) != len(set(listing_keys)):
        raise ValueError("universe listing identities must be unique")


def _validate_member(member: EvidenceUniverseMember, policy: UniverseV2Policy) -> None:
    country = member.country_code.upper()
    if country not in policy.allowed_countries:
        raise ValueError(f"country is outside the universe policy: {country}")
    if not member.exchange_code.strip() or not member.ticker.strip():
        raise ValueError("exchange_code and ticker are required")
    if member.price_source_id == "tiingo-eod" and country != "US":
        raise ValueError("Tiingo universe members must be US-listed")

    if member.universe_kind is UniverseKind.CORE_ETF:
        if member.asset_type is not AssetType.ETF:
            raise ValueError("core_etf members must have ETF asset type")
        if UniverseEvidenceType.ETF_CATALOG not in member.evidence_types:
            raise ValueError("core_etf members require etf_catalog evidence")
        if not member.exposure_key or not member.exposure_key.strip():
            raise ValueError("core_etf members require an exposure_key")
        return

    if member.asset_type is not AssetType.EQUITY:
        raise ValueError("equity universe members must have equity asset type")
    if member.exposure_key is not None:
        raise ValueError("individual equities must not have an exposure_key")

    if member.universe_kind is UniverseKind.INVESTOR_EQUITY:
        if country != "US" or UniverseEvidenceType.SEC_13F not in member.evidence_types:
            raise ValueError("investor equities must be US-listed and have SEC 13F evidence")
        return

    if member.universe_kind is UniverseKind.KRX_INDEX_EQUITY:
        if country != "KR" or not member.evidence_types & policy.krx_equity_evidence:
            raise ValueError("KRX equities require KOSPI 200 or KOSDAQ 150 evidence")
        return

    raise ValueError(f"unsupported universe kind: {member.universe_kind}")


def _positive_int(payload: dict[str, object], name: str) -> int:
    value = payload.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _string_set(payload: dict[str, object], name: str) -> frozenset[str]:
    values = payload.get(name)
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise ValueError(f"{name} must be a list of strings")
    return frozenset(values)

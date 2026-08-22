from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest

from asset_frame.domain.models import AssetType
from asset_frame.ingestion.universe_v2 import (
    EvidenceUniverseMember,
    MembershipStatus,
    UniverseEvidenceType,
    UniverseKind,
    load_universe_v2_policy,
    validate_universe_composition,
)


def _etf(
    number: int,
    *,
    country: str,
    exchange: str,
    ticker: str,
    exposure_key: str = "equity.us.large_cap.sp500",
    source: str | None = None,
) -> EvidenceUniverseMember:
    return EvidenceUniverseMember(
        asset_id=UUID(int=number),
        country_code=country,
        exchange_code=exchange,
        ticker=ticker,
        asset_type=AssetType.ETF,
        universe_kind=UniverseKind.CORE_ETF,
        evidence_types=frozenset({UniverseEvidenceType.ETF_CATALOG}),
        exposure_key=exposure_key,
        price_source_id=source,
    )


def _investor_equity(
    number: int, *, status: MembershipStatus = MembershipStatus.ACTIVE
) -> EvidenceUniverseMember:
    return EvidenceUniverseMember(
        asset_id=UUID(int=number),
        country_code="US",
        exchange_code="NASDAQ",
        ticker=f"US{number}",
        asset_type=AssetType.EQUITY,
        universe_kind=UniverseKind.INVESTOR_EQUITY,
        evidence_types=frozenset({UniverseEvidenceType.SEC_13F}),
        status=status,
        price_source_id="tiingo-eod",
    )


def test_loads_evidence_based_universe_policy() -> None:
    policy = load_universe_v2_policy(Path("config/analysis-universe.toml"))

    assert policy.policy_version == 2
    assert policy.etf_limit == 120
    assert policy.investor_equity_limit == 200
    assert policy.tiingo_monthly_unique_symbol_limit == 400
    assert policy.cooling_quarters == 2
    assert policy.allow_duplicate_exposures is True


def test_allows_same_exposure_for_korean_and_us_etfs() -> None:
    policy = load_universe_v2_policy(Path("config/analysis-universe.toml"))
    members = (
        _etf(1, country="US", exchange="NYSE ARCA", ticker="SPY", source="tiingo-eod"),
        _etf(2, country="KR", exchange="KRX", ticker="379800"),
    )

    summary = validate_universe_composition(members, policy)

    assert summary.active_etfs == 2
    assert summary.tiingo_monthly_unique_symbols == 1


def test_rejects_duplicate_listing_identity_even_when_exposure_duplicates_are_allowed() -> None:
    policy = load_universe_v2_policy(Path("config/analysis-universe.toml"))
    members = (
        _etf(1, country="US", exchange="NYSE ARCA", ticker="SPY"),
        _etf(2, country="us", exchange="nyse arca", ticker="spy"),
    )

    with pytest.raises(ValueError, match="listing identities"):
        validate_universe_composition(members, policy)


def test_rejects_korean_equity_without_target_index_evidence() -> None:
    policy = load_universe_v2_policy(Path("config/analysis-universe.toml"))
    member = EvidenceUniverseMember(
        asset_id=UUID(int=1),
        country_code="KR",
        exchange_code="KRX",
        ticker="005930",
        asset_type=AssetType.EQUITY,
        universe_kind=UniverseKind.KRX_INDEX_EQUITY,
        evidence_types=frozenset(),
    )

    with pytest.raises(ValueError, match="KOSPI 200 or KOSDAQ 150"):
        validate_universe_composition((member,), policy)


def test_counts_cooling_equity_against_tiingo_but_not_active_equity_limit() -> None:
    policy = replace(
        load_universe_v2_policy(Path("config/analysis-universe.toml")),
        investor_equity_limit=1,
    )
    members = (
        _investor_equity(1),
        _investor_equity(2, status=MembershipStatus.COOLING),
    )

    summary = validate_universe_composition(members, policy)

    assert summary.active_investor_equities == 1
    assert summary.tiingo_monthly_unique_symbols == 2


def test_enforces_tiingo_monthly_unique_symbol_limit() -> None:
    policy = replace(
        load_universe_v2_policy(Path("config/analysis-universe.toml")),
        tiingo_monthly_unique_symbol_limit=1,
    )

    with pytest.raises(ValueError, match="Tiingo unique symbol count"):
        validate_universe_composition((_investor_equity(1), _investor_equity(2)), policy)

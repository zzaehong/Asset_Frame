from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from asset_frame.domain.models import AssetType
from asset_frame.ingestion.universe import (
    LiquidityCandidate,
    UniversePolicy,
    load_universe_policy,
    select_analysis_universe,
)


def _candidate(
    number: int,
    *,
    ticker: str,
    asset_type: AssetType = AssetType.EQUITY,
    volume: str | None = "100",
    observations: int = 60,
    pinned: bool = False,
) -> LiquidityCandidate:
    return LiquidityCandidate(
        asset_id=UUID(int=number),
        ticker=ticker,
        asset_type=asset_type,
        median_dollar_volume=Decimal(volume) if volume is not None else None,
        observation_count=observations,
        pinned=pinned,
    )


def test_selects_pinned_then_liquid_candidates_within_type_limit() -> None:
    policy = UniversePolicy(2, 1, 60, 40, Decimal("10"))
    candidates = (
        _candidate(1, ticker="LOW", volume="1", pinned=True),
        _candidate(2, ticker="HIGH", volume="1000"),
        _candidate(3, ticker="MID", volume="500"),
        _candidate(4, ticker="SPY", asset_type=AssetType.ETF, volume="900"),
        _candidate(5, ticker="QQQ", asset_type=AssetType.ETF, volume="800"),
    )

    result = select_analysis_universe(
        country_code="us",
        as_of_date=date(2026, 8, 21),
        candidates=candidates,
        policy=policy,
    )

    assert [item.ticker for item in result.memberships] == ["LOW", "HIGH", "SPY"]
    assert result.memberships[0].selection_reason == "data_spike_pinned"
    assert len(result.input_hash) == 64


def test_excludes_insufficient_history_unless_pinned() -> None:
    policy = UniversePolicy(2, 1, 60, 40, Decimal("10"))
    result = select_analysis_universe(
        country_code="KR",
        as_of_date=date(2026, 8, 21),
        candidates=(
            _candidate(1, ticker="NEW", observations=10),
            _candidate(2, ticker="PIN", volume=None, observations=0, pinned=True),
        ),
        policy=policy,
    )
    assert [item.ticker for item in result.memberships] == ["PIN"]


def test_rejects_duplicate_tickers() -> None:
    policy = UniversePolicy(2, 1, 60, 40, Decimal("10"))
    with pytest.raises(ValueError, match="tickers"):
        select_analysis_universe(
            country_code="US",
            as_of_date=date(2026, 8, 21),
            candidates=(
                _candidate(1, ticker="abc"),
                _candidate(2, ticker="ABC"),
            ),
            policy=policy,
        )


def test_loads_repository_policy() -> None:
    policy = load_universe_policy(Path("config/analysis-universe.toml"))
    assert policy.equity_limit == 500
    assert policy.etf_limit == 150
    assert policy.storage_warning_gb == 10

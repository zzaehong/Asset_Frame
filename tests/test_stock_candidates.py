import tomllib
from pathlib import Path

from asset_frame.universe import load_universe

CANDIDATES = tomllib.loads(Path("config/stock_candidates.toml").read_text())["candidates"]
ETFS = {asset.ticker for asset in load_universe(Path("config/universe.toml"))}


def test_candidate_tickers_are_unique_and_within_the_collection_limit() -> None:
    tickers = [c["ticker"] for c in CANDIDATES]
    assert len(tickers) == len(set(tickers))
    assert 0 < len(tickers) <= 50  # ADR-0010: the whole list could be chosen within the limit


def test_every_candidate_is_a_major_holding_of_a_tracked_etf() -> None:
    for candidate in CANDIDATES:
        assert candidate["etfs"], candidate["ticker"]
        assert set(candidate["etfs"]) <= ETFS, candidate["ticker"]
        assert candidate["name"] and candidate["gics_sector"]


def test_candidates_do_not_overlap_the_etf_universe() -> None:
    assert not {c["ticker"] for c in CANDIDATES} & ETFS

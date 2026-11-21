from datetime import date
from pathlib import Path

import pytest

from asset_frame.stocks import (
    HISTORY_START,
    LIMIT,
    Candidate,
    StockConfigError,
    load_candidates,
    load_stocks,
    stock_summary,
    stock_universe,
)
from asset_frame.universe import load_universe

UNIVERSE = load_universe(Path("config/universe.toml"))
CANDIDATES = (
    Candidate("NVDA", "NVIDIA", "정보기술", ("SPY", "QQQ")),
    Candidate("JPM", "JPMorgan Chase", "금융", ("SPY", "XLF")),
)


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "stocks.toml"
    path.write_text(body)
    return path


def test_missing_file_and_empty_selection_mean_nothing_selected(tmp_path: Path) -> None:
    assert load_stocks(tmp_path / "none.toml", UNIVERSE) == ()
    assert load_stocks(write(tmp_path, "schema_version = 1\n"), UNIVERSE) == ()
    assert load_stocks(Path("config/stocks.toml"), UNIVERSE) == ()  # shipped default


def test_selection_uses_candidate_names_and_normalizes_case(tmp_path: Path) -> None:
    body = (
        'schema_version = 1\n[[stocks]]\nticker = "nvda"\n'
        '[[stocks]]\nticker = "BRK-B"\nname = "Berkshire"\n'
    )
    specs = load_stocks(write(tmp_path, body), UNIVERSE, CANDIDATES)
    assert [(s.ticker, s.name) for s in specs] == [("NVDA", "NVIDIA"), ("BRK-B", "Berkshire")]


@pytest.mark.parametrize(
    "body, message",
    [
        ("schema_version = 2\n", "schema"),
        ('schema_version = 1\n[[stocks]]\nticker = "SPY"\n', "ETF"),
        (
            'schema_version = 1\n[[stocks]]\nticker = "NVDA"\n[[stocks]]\nticker = "NVDA"\n',
            "duplicate",
        ),
        ('schema_version = 1\n[[stocks]]\nticker = "no way"\n', "invalid ticker"),
        ('schema_version = 1\n[[stocks]]\nticker = ""\n', "invalid ticker"),
    ],
)
def test_invalid_selection_is_rejected(tmp_path: Path, body: str, message: str) -> None:
    with pytest.raises(StockConfigError, match=message):
        load_stocks(write(tmp_path, body), UNIVERSE)


def test_more_than_the_limit_is_rejected(tmp_path: Path) -> None:
    tickers = [f"{a}{b}" for a in "ABCDEFGH" for b in "ABCDEFGH"][: LIMIT + 1]
    body = "schema_version = 1\n" + "".join(f'[[stocks]]\nticker = "{t}"\n' for t in tickers)
    with pytest.raises(StockConfigError, match="limit"):
        load_stocks(write(tmp_path, body), UNIVERSE)


def test_collection_entries_start_at_the_history_start() -> None:
    from datetime import timedelta

    from asset_frame.ingestion.universe_service import LOOKBACK_DAYS
    from asset_frame.stocks import StockSpec

    [asset] = stock_universe((StockSpec("NVDA", "NVIDIA"),))
    assert asset.expected_inception - timedelta(days=LOOKBACK_DAYS) == HISTORY_START
    assert asset.group == "stock"


def test_summary_marks_collected_and_keeps_hand_added_selections() -> None:
    from asset_frame.stocks import StockSpec

    seen = {"NVDA": date(2026, 11, 17)}
    summary = stock_summary(
        (StockSpec("NVDA", "NVIDIA"), StockSpec("ZZZ", "Hand added")),
        CANDIDATES,
        seen.get,
        date(2026, 11, 22),
    )
    rows = {r["ticker"]: r for r in summary["candidates"]}
    assert (
        rows["NVDA"]["collected_through"] == "2026-11-17"
        and rows["JPM"]["collected_through"] is None
    )
    assert rows["ZZZ"]["sector"] == "직접 추가" and rows["ZZZ"]["etfs"] == []
    assert summary["selected"] == ["NVDA", "ZZZ"] and summary["limit"] == LIMIT
    # 2010-01-01 .. 2026-11-22 needs two 10-year windows, 75 seconds apart
    assert summary["seconds_per_ticker"] == 150


def test_shipped_candidates_load() -> None:
    assert len(load_candidates(Path("config/stock_candidates.toml"))) > 0


def test_ingesting_a_selection_collects_only_those_tickers_as_equities(tmp_path: Path) -> None:
    from asset_frame.domain.models import AssetType
    from asset_frame.ingestion.universe_service import ingest_universe
    from asset_frame.stocks import StockSpec
    from asset_frame.storage.research import ResearchStore

    calls: list[tuple[str, AssetType, date]] = []

    class Recorder:
        def collect(self, *, ticker, asset_type, start_date, **_):  # type: ignore[no-untyped-def]
            calls.append((ticker, asset_type, start_date))

    store = ResearchStore(tmp_path / "db.sqlite3")
    specs = (StockSpec("NVDA", "NVIDIA"), StockSpec("JPM", "JPMorgan Chase"))
    result = ingest_universe(
        stock_universe(specs),
        collector=Recorder(),  # type: ignore[arg-type]
        store=store,
        api_key="k",
        end_date=date(2026, 11, 20),
        asset_type=AssetType.EQUITY,
        report=lambda _: None,
    )
    assert result.collected == ["NVDA", "JPM"]
    assert {c[0] for c in calls} == {"NVDA", "JPM"}  # nothing else is requested
    assert {c[1] for c in calls} == {AssetType.EQUITY}
    assert min(c[2] for c in calls) == HISTORY_START
    again = ingest_universe(
        stock_universe(specs),
        collector=Recorder(),  # type: ignore[arg-type]
        store=store,
        api_key="k",
        end_date=date(2026, 11, 20),
        asset_type=AssetType.EQUITY,
        report=lambda _: None,
    )
    assert again.skipped == ["NVDA", "JPM"]  # a rerun resumes, it does not refetch

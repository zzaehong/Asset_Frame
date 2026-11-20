import random
from datetime import date, timedelta
from pathlib import Path

from test_universe import TiingoFake, collector

from asset_frame.connectors.tiingo import tiingo_asset_id
from asset_frame.domain.models import AssetType
from asset_frame.ingestion.universe_service import ingest_universe
from asset_frame.proxies import ProxySpec, proxy_universe
from asset_frame.proxy_jobs import build_proxy_returns, merged_returns, spliced_levels
from asset_frame.returns.series import compute_universe_returns
from asset_frame.storage.research import ResearchStore
from asset_frame.universe import UniverseAsset

END = date(2005, 1, 31)


def weekdays(start: date, end: date) -> list[date]:
    days = [start + timedelta(days=n) for n in range((end - start).days + 1)]
    return [d for d in days if d.weekday() < 5]


def walk(days: list[date], seed: int) -> dict[date, float]:
    rng = random.Random(seed)
    level, out = 100.0, {}
    for day in days:
        level *= 1 + rng.gauss(0.0004, 0.01)
        out[day] = level
    return out


def asset(ticker: str, start: date) -> UniverseAsset:
    return UniverseAsset(ticker, ticker, 1, "us_equity", "anchor", None, start, None)


def prepare(tmp_path: Path, proxy_prices: dict[date, float], target_prices: dict[date, float]):
    store = ResearchStore(tmp_path / "db.sqlite3")
    spec = ProxySpec("SPY", "VFINX", "fund", date(1999, 1, 4), "index")
    ingest_universe(
        (asset("SPY", date(2001, 1, 2)),),
        collector=collector(tmp_path, TiingoFake(date(2001, 1, 2), target_prices)),
        store=store,
        api_key="k",
        end_date=END,
        report=lambda _: None,
    )
    ingest_universe(
        proxy_universe((spec,)),
        collector=collector(tmp_path, TiingoFake(date(1999, 1, 4), proxy_prices)),
        store=store,
        api_key="k",
        end_date=END,
        asset_type=AssetType.MUTUAL_FUND,
        report=lambda _: None,
    )
    built = compute_universe_returns(
        {"SPY": store.price_points(tiingo_asset_id("SPY"))},
        calendar_ticker="SPY",
        cash_ticker="BIL",
        cash_proxy=[],
    )
    store.save_build(built.returns, built.anomalies, calc_version="test")
    return store, spec


def test_a_tracking_proxy_fills_only_months_before_the_etf_and_is_flagged(tmp_path: Path) -> None:
    days = weekdays(date(1999, 1, 4), END)
    proxy = walk(days, seed=1)
    target = {d: v * 0.5 for d, v in proxy.items() if d >= date(2001, 1, 2)}  # same moves
    store, spec = prepare(tmp_path, proxy, target)

    returns, checks, _ = build_proxy_returns((spec,), store=store)

    assert checks[0].used and checks[0].overlap_months >= 36
    assert abs(checks[0].annual_tracking_difference or 0) < 1e-6
    months = sorted(item.month_end for item in returns["SPY"])
    etf_first = min(store.latest_returns()["SPY"])
    assert months and months[-1] < etf_first
    assert all(
        item.is_proxy and "proxy:VFINX" in item.source_price_version for item in returns["SPY"]
    )

    store.save_proxy_build(
        returns, checks, proxy_by_target={"SPY": ("VFINX", "index")}, calc_version="test"
    )
    merged = merged_returns(store)["SPY"]
    assert min(merged) == months[0]
    assert {m: merged[m] for m in store.latest_returns()["SPY"]} == store.latest_returns()["SPY"]
    levels = spliced_levels((spec,), store=store, ticker="SPY")
    assert levels[0][0] == date(1999, 1, 4) and levels[-1][0] == END


def test_a_proxy_that_does_not_track_is_not_used_and_says_why(tmp_path: Path) -> None:
    days = weekdays(date(1999, 1, 4), END)
    proxy = walk(days, seed=1)
    target = {d: v for d, v in walk(days, seed=2).items() if d >= date(2001, 1, 2)}
    store, spec = prepare(tmp_path, proxy, target)

    returns, checks, _ = build_proxy_returns((spec,), store=store)

    assert not checks[0].used and "correlation" in checks[0].reason
    assert returns == {}
    store.save_proxy_build(
        returns, checks, proxy_by_target={"SPY": ("VFINX", "index")}, calc_version="test"
    )
    assert merged_returns(store)["SPY"] == store.latest_returns()["SPY"]
    assert [row.used for row in store.latest_proxy_checks()] == [False]


def test_missing_proxy_prices_are_reported_not_raised(tmp_path: Path) -> None:
    store = ResearchStore(tmp_path / "db.sqlite3")
    spec = ProxySpec("SPY", "VFINX", "fund", date(1999, 1, 4), "index")
    days = weekdays(date(2001, 1, 2), END)
    target = walk(days, seed=3)
    ingest_universe(
        (asset("SPY", date(2001, 1, 2)),),
        collector=collector(tmp_path, TiingoFake(date(2001, 1, 2), target)),
        store=store,
        api_key="k",
        end_date=END,
        report=lambda _: None,
    )
    built = compute_universe_returns(
        {"SPY": store.price_points(tiingo_asset_id("SPY"))},
        calendar_ticker="SPY",
        cash_ticker="BIL",
        cash_proxy=[],
    )
    store.save_build(built.returns, built.anomalies, calc_version="test")

    returns, checks, _ = build_proxy_returns((spec,), store=store)

    assert returns == {} and not checks[0].used and "no prices" in checks[0].reason

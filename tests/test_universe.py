import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from asset_frame.domain.models import FetchResponse
from asset_frame.ingestion.tiingo_service import TiingoEodCollector
from asset_frame.ingestion.universe_service import collection_windows, ingest_universe
from asset_frame.sources.registry import load_source_registry
from asset_frame.storage.raw import FileRawStore
from asset_frame.storage.research import ResearchStore
from asset_frame.storage.sqlite import SqliteIngestionRepository
from asset_frame.universe import (
    UniverseAsset,
    UniverseConfigError,
    compare_inception,
    load_universe,
    validate_universe,
)
from asset_frame.universe_jobs import verify_universe

UNIVERSE = load_universe(Path("config/universe.toml"))


def asset(ticker: str, group: str, role: str = "anchor", refines: str | None = None):
    return UniverseAsset(ticker, ticker, 1, group, role, refines, date(2005, 1, 1), None)


def test_project_universe_matches_prd_v3() -> None:
    assert len(UNIVERSE) == 31
    by_ticker = {item.ticker: item for item in UNIVERSE}
    assert sorted(t for t, a in by_ticker.items() if a.role == "granular") == [
        "SCHD",
        "SHYG",
        "VCIT",
        "VCLT",
        "VCSH",
        "VIG",
        "XLC",
        "XLRE",
    ]
    assert by_ticker["VCSH"].refines == "LQD"
    assert by_ticker["SPY"].expected_inception == date(1993, 1, 1)


def test_duplicate_ticker_is_rejected() -> None:
    with pytest.raises(UniverseConfigError, match="unique"):
        validate_universe((asset("SPY", "us_equity"), asset("SPY", "us_equity")))


def test_granular_must_refine_an_anchor_of_the_same_group() -> None:
    with pytest.raises(UniverseConfigError, match="refines"):
        validate_universe(
            (
                asset("LQD", "ig_credit"),
                asset("HYG", "hy_credit"),
                asset("VCSH", "ig_credit", "granular", "HYG"),
            )
        )


def test_each_group_has_exactly_one_anchor_except_gics_sector() -> None:
    with pytest.raises(UniverseConfigError, match="exactly 1"):
        validate_universe((asset("SHY", "treasury"), asset("IEF", "treasury")))
    sectors = tuple(asset(f"XL{letter}", "gics_sector") for letter in "BEFIKPUVY")
    validate_universe(sectors)
    with pytest.raises(UniverseConfigError, match="exactly 9"):
        validate_universe(sectors[:8])


@pytest.mark.parametrize(
    ("offset_days", "status"), [(0, "ok"), (31, "ok"), (-31, "ok"), (32, "mismatch")]
)
def test_inception_tolerance_boundary(offset_days: int, status: str) -> None:
    expected = date(2007, 5, 1)
    actual = expected + timedelta(days=offset_days)

    assert compare_inception("BIL", expected, actual, actual).status == status


def test_inception_mismatch_when_either_date_is_off_or_missing() -> None:
    expected = date(2007, 5, 1)
    assert compare_inception("BIL", expected, expected, date(2008, 1, 2)).status == "mismatch"
    assert compare_inception("BIL", expected, None, expected).status == "mismatch"


def test_collection_windows_overlap_and_fit_ten_years() -> None:
    windows = collection_windows(date(1992, 1, 1), date(2026, 11, 17))

    assert windows[0][0] == date(1992, 1, 1)
    assert windows[-1][1] == date(2026, 11, 17)
    for (_, previous_end), (next_start, next_end) in zip(windows, windows[1:], strict=False):
        assert next_start < previous_end
        assert next_end.replace(year=next_end.year - 10) <= next_start


class TiingoFake:
    """Serves metadata then one price row per window, with the listing date as startDate."""

    def __init__(self, listing: date, adj_closes: dict[date, float]) -> None:
        self.listing = listing
        self.adj_closes = adj_closes
        self.requests = 0

    def fetch(self, request):  # type: ignore[no-untyped-def]
        self.requests += 1
        if "/prices?" not in request.url:
            body = {
                "ticker": request.url.rsplit("/", 1)[1],
                "name": "Fake",
                "exchangeCode": "NYSE ARCA",
                "startDate": self.listing.isoformat(),
            }
        else:
            query = dict(part.split("=") for part in request.url.split("?")[1].split("&"))
            start, end = (
                date.fromisoformat(query["startDate"]),
                date.fromisoformat(query["endDate"]),
            )
            body = [
                {
                    "date": f"{day.isoformat()}T00:00:00.000Z",
                    "open": value,
                    "high": value,
                    "low": value,
                    "close": value,
                    "volume": 1,
                    "adjClose": value,
                    "divCash": 0.0,
                    "splitFactor": 1.0,
                }
                for day, value in self.adj_closes.items()
                if start <= day <= end
            ]
        return FetchResponse(200, json.dumps(body).encode(), {}, datetime(2026, 11, 18, tzinfo=UTC))


def collector(tmp_path: Path, transport: TiingoFake) -> TiingoEodCollector:
    source = next(
        item
        for item in load_source_registry(Path("config/sources.toml"))
        if item.id == "tiingo-eod"
    )
    return TiingoEodCollector(
        source=source,
        transport=transport,
        raw_store=FileRawStore(tmp_path / "raw"),
        repository=SqliteIngestionRepository(tmp_path / "db.sqlite3"),
    )


def test_verify_writes_only_ok_rows_to_config(tmp_path: Path) -> None:
    config = tmp_path / "universe.toml"
    config.write_text(Path("config/universe.toml").read_text())
    store = ResearchStore(tmp_path / "db.sqlite3")
    spy = replace(next(a for a in UNIVERSE if a.ticker == "SPY"))
    bil = replace(next(a for a in UNIVERSE if a.ticker == "BIL"))
    end = date(2007, 9, 1)
    ingest_universe(
        (spy,),
        collector=collector(tmp_path, TiingoFake(date(1993, 1, 29), {date(1993, 1, 29): 1.0})),
        store=store,
        api_key="secret",
        end_date=end,
        report=lambda _: None,
    )
    ingest_universe(
        (bil,),
        collector=collector(tmp_path, TiingoFake(date(2007, 8, 1), {date(2007, 8, 1): 1.0})),
        store=store,
        api_key="secret",
        end_date=end,
        report=lambda _: None,
    )

    checks = verify_universe((spy, bil), store=store, raw_root=tmp_path / "raw", config_path=config)

    assert [(c.ticker, c.status) for c in checks] == [("SPY", "ok"), ("BIL", "mismatch")]
    reloaded = {a.ticker: a for a in load_universe(config)}
    assert reloaded["SPY"].verified_inception == date(1993, 1, 29)
    assert reloaded["BIL"].verified_inception is None


def test_ingest_resumes_from_the_failed_ticker(tmp_path: Path) -> None:
    store = ResearchStore(tmp_path / "db.sqlite3")
    calls: list[str] = []

    class FlakyCollector:
        fail_once = True

        def collect(self, *, ticker, **_):  # type: ignore[no-untyped-def]
            calls.append(ticker)
            if ticker == "IEF" and self.fail_once:
                self.fail_once = False
                raise RuntimeError("Tiingo prices returned HTTP 429")

    fake = FlakyCollector()
    assets = tuple(a for a in UNIVERSE if a.ticker in ("SHY", "IEF"))
    first = ingest_universe(
        assets,
        collector=fake,  # type: ignore[arg-type]
        store=store,
        api_key="k",
        end_date=date(2026, 11, 17),
        report=lambda _: None,
    )
    calls.clear()
    second = ingest_universe(
        assets,
        collector=fake,  # type: ignore[arg-type]
        store=store,
        api_key="k",
        end_date=date(2026, 11, 17),
        report=lambda _: None,
    )

    assert (first.collected, list(first.failed)) == (["SHY"], ["IEF"])
    assert (second.skipped, second.collected) == (["SHY"], ["IEF"])
    assert set(calls) == {"IEF"}

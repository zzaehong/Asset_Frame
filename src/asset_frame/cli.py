from __future__ import annotations

import argparse
import csv
import os
from dataclasses import astuple, fields
from datetime import UTC, date, datetime
from pathlib import Path

from asset_frame.connectors.fred import FRED_SOURCE_ID, SUPPORTED_SERIES
from asset_frame.connectors.krx import KRX_SOURCE_ID, KrxDataset
from asset_frame.connectors.tiingo import TIINGO_SOURCE_ID
from asset_frame.domain.models import AssetType, SourceDefinition
from asset_frame.ingestion.fred_service import FredCollector
from asset_frame.ingestion.krx_service import KrxCollector
from asset_frame.ingestion.tiingo_service import TiingoEodCollector
from asset_frame.ingestion.transport import RateLimitedRetryTransport, UrllibHttpTransport
from asset_frame.ingestion.universe_service import ingest_universe
from asset_frame.sources.registry import load_source_registry
from asset_frame.storage.raw import FileRawStore
from asset_frame.storage.research import ResearchStore
from asset_frame.storage.sqlite import SqliteIngestionRepository
from asset_frame.universe import load_universe
from asset_frame.universe_jobs import StatusRow, build_returns, universe_status, verify_universe

SOURCES_PATH = Path("config/sources.toml")
UNIVERSE_PATH = Path("config/universe.toml")
STATUS_CSV_PATH = Path("var/reports/universe_status.csv")
DEFAULT_DATABASE_PATH = "var/asset_frame.sqlite3"
DEFAULT_RAW_STORE_PATH = "var/raw"
# Tiingo Starter plan allows 50 requests/hour (config/sources.toml); 75 s keeps us at 48.
TIINGO_STARTER_INTERVAL_SECONDS = 75.0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="asset-frame")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("sources", help="list registered data sources")

    tiingo_parser = subparsers.add_parser(
        "ingest-tiingo", help="collect Tiingo metadata and EOD prices"
    )
    tiingo_parser.add_argument("--ticker", required=True)
    tiingo_parser.add_argument("--asset-type", required=True, choices=("equity", "etf"))
    tiingo_parser.add_argument("--start-date", required=True, type=date.fromisoformat)
    tiingo_parser.add_argument("--end-date", required=True, type=date.fromisoformat)

    krx_parser = subparsers.add_parser("ingest-krx", help="collect an approved KRX dataset")
    krx_parser.add_argument(
        "--dataset", required=True, choices=[item.name.lower() for item in KrxDataset]
    )
    krx_parser.add_argument("--date", required=True, type=date.fromisoformat)

    universe_ingest_parser = subparsers.add_parser(
        "ingest-universe", help="collect full Tiingo history for every universe ticker"
    )
    universe_ingest_parser.add_argument(
        "--end-date", type=date.fromisoformat, default=datetime.now(UTC).date()
    )
    universe_ingest_parser.add_argument(
        "--min-interval-seconds", type=float, default=TIINGO_STARTER_INTERVAL_SECONDS
    )

    universe_parser = subparsers.add_parser("universe", help="universe verification and status")
    universe_commands = universe_parser.add_subparsers(dest="universe_command", required=True)
    universe_commands.add_parser("verify", help="compare inception dates with Tiingo data")
    universe_commands.add_parser("status", help="print per-ticker data status")

    fred_parser = subparsers.add_parser("ingest-fred", help="collect a FRED series")
    fred_parser.add_argument("--series", required=True, choices=SUPPORTED_SERIES)

    subparsers.add_parser("build-returns", help="compute monthly total returns")

    arguments = parser.parse_args(argv)
    if arguments.command == "sources":
        _print_sources()
    elif arguments.command == "ingest-tiingo":
        _ingest_tiingo(
            arguments.ticker, arguments.asset_type, arguments.start_date, arguments.end_date
        )
    elif arguments.command == "ingest-krx":
        _ingest_krx(arguments.dataset, arguments.date)
    elif arguments.command == "ingest-universe":
        _ingest_universe(arguments.end_date, arguments.min_interval_seconds)
    elif arguments.command == "universe" and arguments.universe_command == "verify":
        _verify_universe()
    elif arguments.command == "universe":
        _print_universe_status()
    elif arguments.command == "ingest-fred":
        _ingest_fred(arguments.series)
    elif arguments.command == "build-returns":
        _build_returns()


def _print_sources() -> None:
    for source in load_source_registry(SOURCES_PATH):
        kinds = ",".join(kind.value for kind in source.data_kinds)
        print(
            f"{source.id}\t{source.implementation_status.value}\t"
            f"{'enabled' if source.enabled else 'disabled'}\t{source.authority}\t{kinds}"
        )


def _ingest_tiingo(ticker: str, asset_type_name: str, start_date: date, end_date: date) -> None:
    api_key = _required_environment("TIINGO_API_KEY")
    collector = TiingoEodCollector(
        source=_source(TIINGO_SOURCE_ID),
        transport=UrllibHttpTransport(),
        raw_store=_raw_store(),
        repository=_repository(),
    )
    result = collector.collect(
        ticker=ticker,
        asset_type=AssetType(asset_type_name),
        api_key=api_key,
        start_date=start_date,
        end_date=end_date,
    )
    print(
        f"collected Tiingo {ticker.upper()}: {result.accepted_prices} prices, "
        f"{result.quarantined_prices} quarantined, "
        f"{result.corporate_actions} corporate actions; asset {result.asset.id}"
    )


def _ingest_krx(dataset_name: str, business_date: date) -> None:
    api_key = _required_environment("KRX_API_KEY")
    collector = KrxCollector(
        source=_source(KRX_SOURCE_ID),
        transport=UrllibHttpTransport(),
        raw_store=_raw_store(),
        repository=_repository(),
    )
    count = collector.collect(
        dataset=KrxDataset[dataset_name.upper()], business_date=business_date, api_key=api_key
    )
    print(f"collected {count} KRX {dataset_name} rows for {business_date.isoformat()}")


def _ingest_universe(end_date: date, min_interval_seconds: float) -> None:
    api_key = _required_environment("TIINGO_API_KEY")
    collector = TiingoEodCollector(
        source=_source(TIINGO_SOURCE_ID),
        transport=RateLimitedRetryTransport(
            UrllibHttpTransport(), minimum_interval_seconds=min_interval_seconds
        ),
        raw_store=_raw_store(),
        repository=_repository(),
    )
    result = ingest_universe(
        load_universe(UNIVERSE_PATH),
        collector=collector,
        store=_research_store(),
        api_key=api_key,
        end_date=end_date,
    )
    print(
        f"universe ingest through {end_date}: {len(result.collected)} collected, "
        f"{len(result.skipped)} already done, {len(result.failed)} failed"
    )
    if result.failed:
        raise SystemExit("rerun the same command to resume failed tickers")


def _verify_universe() -> None:
    checks = verify_universe(
        load_universe(UNIVERSE_PATH),
        store=_research_store(),
        raw_root=Path(os.getenv("RAW_STORE_PATH") or DEFAULT_RAW_STORE_PATH),
        config_path=UNIVERSE_PATH,
    )
    for check in checks:
        print(
            f"{check.ticker}\t{check.status}\texpected={check.expected.strftime('%Y-%m')}\t"
            f"provider_start={check.provider_start or '-'}\t"
            f"first_price={check.first_price_date or '-'}"
        )
    mismatches = [check.ticker for check in checks if check.status == "mismatch"]
    print(f"ok {len(checks) - len(mismatches)}, mismatch {len(mismatches)}")
    if mismatches:
        print("mismatch rows were not written to config; review: " + " ".join(mismatches))


def _print_universe_status() -> None:
    rows = universe_status(load_universe(UNIVERSE_PATH), store=_research_store())
    header = [field.name for field in fields(StatusRow)]
    table = [header] + [[_cell(value) for value in astuple(row)] for row in rows]
    widths = [max(len(line[column]) for line in table) for column in range(len(header))]
    for line in table:
        print("  ".join(cell.ljust(width) for cell, width in zip(line, widths, strict=True)))
    STATUS_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with STATUS_CSV_PATH.open("w", newline="") as csv_file:
        csv.writer(csv_file).writerows(table)
    print(f"wrote {STATUS_CSV_PATH}")


def _ingest_fred(series_id: str) -> None:
    api_key = _required_environment("FRED_API_KEY")
    collector = FredCollector(
        source=_source(FRED_SOURCE_ID),
        transport=UrllibHttpTransport(),
        raw_store=_raw_store(),
        repository=_repository(),
    )
    count = collector.collect(series_id=series_id, api_key=api_key)
    print(f"collected {count} FRED {series_id} observations")


def _build_returns() -> None:
    result, computed_at = build_returns(load_universe(UNIVERSE_PATH), store=_research_store())
    months = sum(len(items) for items in result.returns.values())
    anomalies = sum(len(items) for items in result.anomalies.values())
    print(f"built {months} monthly returns, {anomalies} anomalies at {computed_at}")
    for ticker, reason in result.failures.items():
        print(f"{ticker}: not built ({reason})")
    if not any(item.is_proxy for items in result.returns.values() for item in items):
        print("no DTB3 cash proxy months: run `asset-frame ingest-fred --series DTB3` first")


def _cell(value: object) -> str:
    return "-" if value is None else str(value)


def _source(source_id: str) -> SourceDefinition:
    return next(source for source in load_source_registry(SOURCES_PATH) if source.id == source_id)


def _database_path() -> Path:
    return Path(os.getenv("DATABASE_PATH") or DEFAULT_DATABASE_PATH)


def _repository() -> SqliteIngestionRepository:
    return SqliteIngestionRepository(_database_path())


def _research_store() -> ResearchStore:
    return ResearchStore(_database_path())


def _raw_store() -> FileRawStore:
    return FileRawStore(Path(os.getenv("RAW_STORE_PATH") or DEFAULT_RAW_STORE_PATH))


def _required_environment(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"required environment variable is missing: {name}")
    return value

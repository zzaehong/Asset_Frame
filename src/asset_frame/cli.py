from __future__ import annotations

import argparse
import os
from datetime import date
from pathlib import Path

from asset_frame.connectors.krx import KRX_SOURCE_ID, KrxDataset
from asset_frame.connectors.tiingo import TIINGO_SOURCE_ID
from asset_frame.domain.models import AssetType, SourceDefinition
from asset_frame.ingestion.krx_service import KrxCollector
from asset_frame.ingestion.tiingo_service import TiingoEodCollector
from asset_frame.ingestion.transport import UrllibHttpTransport
from asset_frame.sources.registry import load_source_registry
from asset_frame.storage.raw import FileRawStore
from asset_frame.storage.sqlite import SqliteIngestionRepository

SOURCES_PATH = Path("config/sources.toml")
DEFAULT_DATABASE_PATH = "var/asset_frame.sqlite3"
DEFAULT_RAW_STORE_PATH = "var/raw"


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

    arguments = parser.parse_args(argv)
    if arguments.command == "sources":
        _print_sources()
    elif arguments.command == "ingest-tiingo":
        _ingest_tiingo(
            arguments.ticker, arguments.asset_type, arguments.start_date, arguments.end_date
        )
    elif arguments.command == "ingest-krx":
        _ingest_krx(arguments.dataset, arguments.date)


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


def _source(source_id: str) -> SourceDefinition:
    return next(source for source in load_source_registry(SOURCES_PATH) if source.id == source_id)


def _repository() -> SqliteIngestionRepository:
    return SqliteIngestionRepository(Path(os.getenv("DATABASE_PATH") or DEFAULT_DATABASE_PATH))


def _raw_store() -> FileRawStore:
    return FileRawStore(Path(os.getenv("RAW_STORE_PATH") or DEFAULT_RAW_STORE_PATH))


def _required_environment(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"required environment variable is missing: {name}")
    return value

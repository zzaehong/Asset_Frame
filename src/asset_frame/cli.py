from __future__ import annotations

import argparse
import os
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from uuid import UUID

import psycopg

from asset_frame.connectors.krx import KrxDataset
from asset_frame.domain.models import AssetType
from asset_frame.ingestion.krx_service import KrxCollector
from asset_frame.ingestion.opendart_service import OpenDartDisclosureCollector
from asset_frame.ingestion.service import SecSubmissionsCollector
from asset_frame.ingestion.tiingo_service import TiingoEodCollector
from asset_frame.ingestion.transport import UrllibHttpTransport
from asset_frame.sources.registry import load_source_registry
from asset_frame.storage.postgres import PostgresIngestionRepository
from asset_frame.storage.raw import FileRawStore


def main() -> None:
    parser = argparse.ArgumentParser(prog="asset-frame")
    subparsers = parser.add_subparsers(dest="command", required=True)
    sec_parser = subparsers.add_parser("collect-sec", help="collect SEC submissions")
    sec_parser.add_argument("--cik", required=True)
    sec_parser.add_argument("--asset-id", required=True, type=UUID)
    sec_parser.add_argument("--raw-store", type=Path, default=Path("var/raw"))
    krx_parser = subparsers.add_parser("collect-krx", help="collect an approved KRX dataset")
    krx_parser.add_argument(
        "--dataset", required=True, choices=[item.name.lower() for item in KrxDataset]
    )
    krx_parser.add_argument("--date", required=True, type=date.fromisoformat)
    krx_parser.add_argument("--raw-store", type=Path, default=Path("var/raw"))
    dart_parser = subparsers.add_parser("collect-opendart", help="collect OpenDART disclosures")
    dart_parser.add_argument("--corp-code", required=True)
    dart_parser.add_argument("--asset-id", required=True, type=UUID)
    dart_parser.add_argument("--start-date", required=True, type=date.fromisoformat)
    dart_parser.add_argument("--end-date", required=True, type=date.fromisoformat)
    dart_parser.add_argument("--raw-store", type=Path, default=Path("var/raw"))
    tiingo_parser = subparsers.add_parser(
        "collect-tiingo", help="collect Tiingo metadata and EOD prices"
    )
    tiingo_parser.add_argument("--ticker", required=True)
    tiingo_parser.add_argument("--asset-type", required=True, choices=("equity", "etf"))
    tiingo_parser.add_argument("--start-date", required=True, type=date.fromisoformat)
    tiingo_parser.add_argument("--end-date", required=True, type=date.fromisoformat)
    tiingo_parser.add_argument("--raw-store", type=Path, default=Path("var/raw"))
    arguments = parser.parse_args()

    if arguments.command == "collect-sec":
        _collect_sec(arguments.cik, arguments.asset_id, arguments.raw_store)
    elif arguments.command == "collect-krx":
        _collect_krx(arguments.dataset, arguments.date, arguments.raw_store)
    elif arguments.command == "collect-opendart":
        _collect_opendart(
            arguments.corp_code,
            arguments.asset_id,
            arguments.start_date,
            arguments.end_date,
            arguments.raw_store,
        )
    elif arguments.command == "collect-tiingo":
        _collect_tiingo(
            arguments.ticker,
            arguments.asset_type,
            arguments.start_date,
            arguments.end_date,
            arguments.raw_store,
        )


def _collect_sec(cik: str, asset_id: UUID, raw_store_path: Path) -> None:
    database_url = _required_environment("DATABASE_URL")
    user_agent = _required_environment("SEC_USER_AGENT")
    source = next(
        source
        for source in load_source_registry(Path("config/sources.toml"))
        if source.id == "sec-edgar-submissions"
    )

    @contextmanager
    def connection_factory():  # type: ignore[no-untyped-def]
        with psycopg.connect(database_url) as connection:
            yield connection

    collector = SecSubmissionsCollector(
        source=source,
        transport=UrllibHttpTransport(),
        raw_store=FileRawStore(raw_store_path),
        repository=PostgresIngestionRepository(connection_factory),
    )
    filings = collector.collect(cik=cik, asset_id=asset_id, user_agent=user_agent)
    print(f"collected {len(filings)} SEC filings for asset {asset_id}")


def _required_environment(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"required environment variable is missing: {name}")
    return value


def _collect_krx(dataset_name: str, business_date: date, raw_store_path: Path) -> None:
    database_url = _required_environment("DATABASE_URL")
    api_key = _required_environment("KRX_API_KEY")
    source = next(
        source
        for source in load_source_registry(Path("config/sources.toml"))
        if source.id == "krx-open-api"
    )

    @contextmanager
    def connection_factory():  # type: ignore[no-untyped-def]
        with psycopg.connect(database_url) as connection:
            yield connection

    collector = KrxCollector(
        source=source,
        transport=UrllibHttpTransport(),
        raw_store=FileRawStore(raw_store_path),
        repository=PostgresIngestionRepository(connection_factory),
    )
    dataset = KrxDataset[dataset_name.upper()]
    count = collector.collect(dataset=dataset, business_date=business_date, api_key=api_key)
    print(f"collected {count} KRX {dataset_name} rows for {business_date.isoformat()}")


def _collect_opendart(
    corp_code: str,
    asset_id: UUID,
    start_date: date,
    end_date: date,
    raw_store_path: Path,
) -> None:
    database_url = _required_environment("DATABASE_URL")
    api_key = _required_environment("OPENDART_API_KEY")
    source = next(
        source
        for source in load_source_registry(Path("config/sources.toml"))
        if source.id == "opendart"
    )

    @contextmanager
    def connection_factory():  # type: ignore[no-untyped-def]
        with psycopg.connect(database_url) as connection:
            yield connection

    collector = OpenDartDisclosureCollector(
        source=source,
        transport=UrllibHttpTransport(),
        raw_store=FileRawStore(raw_store_path),
        repository=PostgresIngestionRepository(connection_factory),
    )
    filings = collector.collect(
        api_key=api_key,
        corp_code=corp_code,
        asset_id=asset_id,
        start_date=start_date,
        end_date=end_date,
    )
    print(f"collected {len(filings)} OpenDART disclosures for asset {asset_id}")


def _collect_tiingo(
    ticker: str,
    asset_type_name: str,
    start_date: date,
    end_date: date,
    raw_store_path: Path,
) -> None:
    database_url = _required_environment("DATABASE_URL")
    api_key = _required_environment("TIINGO_API_KEY")
    source = next(
        source
        for source in load_source_registry(Path("config/sources.toml"))
        if source.id == "tiingo-eod"
    )

    @contextmanager
    def connection_factory():  # type: ignore[no-untyped-def]
        with psycopg.connect(database_url) as connection:
            yield connection

    collector = TiingoEodCollector(
        source=source,
        transport=UrllibHttpTransport(),
        raw_store=FileRawStore(raw_store_path),
        repository=PostgresIngestionRepository(connection_factory),
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

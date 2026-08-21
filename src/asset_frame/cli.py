from __future__ import annotations

import argparse
import os
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID

import psycopg

from asset_frame.connectors.krx import KrxDataset
from asset_frame.domain.models import AssetType, DataKind, IdentifierType
from asset_frame.ingestion.data_spike import (
    evaluate_data_spike_readiness,
    load_data_spike_manifest,
)
from asset_frame.ingestion.freshness import evaluate_freshness
from asset_frame.ingestion.identifier_service import (
    IdentifierMappingResult,
    RegulatoryIdentifierCollector,
)
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
    sec_ids_parser = subparsers.add_parser(
        "collect-sec-identifiers", help="map existing US ticker assets to SEC CIKs"
    )
    sec_ids_parser.add_argument("--raw-store", type=Path, default=Path("var/raw"))
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
    dart_ids_parser = subparsers.add_parser(
        "collect-opendart-identifiers",
        help="map existing Korean ticker assets to OpenDART corp codes",
    )
    dart_ids_parser.add_argument("--raw-store", type=Path, default=Path("var/raw"))
    tiingo_parser = subparsers.add_parser(
        "collect-tiingo", help="collect Tiingo metadata and EOD prices"
    )
    tiingo_parser.add_argument("--ticker", required=True)
    tiingo_parser.add_argument("--asset-type", required=True, choices=("equity", "etf"))
    tiingo_parser.add_argument("--start-date", required=True, type=date.fromisoformat)
    tiingo_parser.add_argument("--end-date", required=True, type=date.fromisoformat)
    tiingo_parser.add_argument("--raw-store", type=Path, default=Path("var/raw"))
    status_parser = subparsers.add_parser(
        "source-status", help="show last successful ingestion and stale status"
    )
    status_parser.add_argument("--source-id", required=True)
    status_parser.add_argument(
        "--data-kind", required=True, choices=[data_kind.value for data_kind in DataKind]
    )
    status_parser.add_argument("--max-age-hours", required=True, type=float)
    spike_parser = subparsers.add_parser(
        "data-spike-status", help="check registration and regulatory identifiers for 20 assets"
    )
    spike_parser.add_argument("--manifest", type=Path, default=Path("config/data-spike.toml"))
    arguments = parser.parse_args()

    if arguments.command == "collect-sec":
        _collect_sec(arguments.cik, arguments.asset_id, arguments.raw_store)
    elif arguments.command == "collect-sec-identifiers":
        _collect_sec_identifiers(arguments.raw_store)
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
    elif arguments.command == "collect-opendart-identifiers":
        _collect_opendart_identifiers(arguments.raw_store)
    elif arguments.command == "collect-tiingo":
        _collect_tiingo(
            arguments.ticker,
            arguments.asset_type,
            arguments.start_date,
            arguments.end_date,
            arguments.raw_store,
        )
    elif arguments.command == "source-status":
        _show_source_status(
            arguments.source_id,
            arguments.data_kind,
            arguments.max_age_hours,
        )
    elif arguments.command == "data-spike-status":
        _show_data_spike_status(arguments.manifest)


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


def _collect_sec_identifiers(raw_store_path: Path) -> None:
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

    collector = RegulatoryIdentifierCollector(
        source=source,
        country_code="US",
        target_identifier_type=IdentifierType.CIK,
        transport=UrllibHttpTransport(),
        raw_store=FileRawStore(raw_store_path),
        repository=PostgresIngestionRepository(connection_factory),
    )
    result = collector.collect_sec(user_agent=user_agent)
    _print_identifier_result("SEC", result)


def _collect_opendart_identifiers(raw_store_path: Path) -> None:
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

    collector = RegulatoryIdentifierCollector(
        source=source,
        country_code="KR",
        target_identifier_type=IdentifierType.DART_CORP_CODE,
        transport=UrllibHttpTransport(),
        raw_store=FileRawStore(raw_store_path),
        repository=PostgresIngestionRepository(connection_factory),
    )
    result = collector.collect_opendart(api_key=api_key)
    _print_identifier_result("OpenDART", result)


def _print_identifier_result(provider: str, result: IdentifierMappingResult) -> None:
    print(
        f"mapped {result.assets_mapped}/{result.assets_considered} existing assets from "
        f"{result.records_received} {provider} records; missing={len(result.assets_missing)}"
    )
    if result.assets_missing:
        print(f"missing tickers: {', '.join(result.assets_missing)}")


def _show_source_status(source_id: str, data_kind: str, max_age_hours: float) -> None:
    database_url = _required_environment("DATABASE_URL")

    @contextmanager
    def connection_factory():  # type: ignore[no-untyped-def]
        with psycopg.connect(database_url) as connection:
            yield connection

    repository = PostgresIngestionRepository(connection_factory)
    status = evaluate_freshness(
        last_success_at=repository.latest_successful_run(source_id=source_id, data_kind=data_kind),
        as_of=datetime.now(UTC),
        max_age=timedelta(hours=max_age_hours),
    )
    last_success = status.last_success_at.isoformat() if status.last_success_at else "none"
    print(
        f"source={source_id} data_kind={data_kind} last_success={last_success} "
        f"stale={str(status.stale).lower()} reason={status.reason}"
    )


def _show_data_spike_status(manifest_path: Path) -> None:
    database_url = _required_environment("DATABASE_URL")

    @contextmanager
    def connection_factory():  # type: ignore[no-untyped-def]
        with psycopg.connect(database_url) as connection:
            yield connection

    manifest = load_data_spike_manifest(manifest_path)
    readiness = evaluate_data_spike_readiness(
        PostgresIngestionRepository(connection_factory), manifest
    )
    print(
        f"Data Spike assets={readiness.assets_registered}/{readiness.total_assets} "
        f"required_identifiers={readiness.required_identifiers_ready}/"
        f"{readiness.total_assets}"
    )
    if readiness.missing_assets:
        print(f"missing assets: {', '.join(readiness.missing_assets)}")
    if readiness.missing_required_identifiers:
        print(f"missing required identifiers: {', '.join(readiness.missing_required_identifiers)}")
    if readiness.asset_type_mismatches:
        print(f"asset type mismatches: {', '.join(readiness.asset_type_mismatches)}")

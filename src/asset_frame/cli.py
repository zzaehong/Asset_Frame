from __future__ import annotations

import argparse
import os
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import psycopg

from asset_frame.connectors.krx import KrxDataset
from asset_frame.domain.models import AssetType, DataKind, IdentifierType
from asset_frame.ingestion.available_batch import AvailableUniverseCollectionService
from asset_frame.ingestion.data_spike import (
    evaluate_data_spike_readiness,
    load_data_spike_manifest,
)
from asset_frame.ingestion.environment import ENVIRONMENT_REQUIREMENTS
from asset_frame.ingestion.freshness import evaluate_freshness
from asset_frame.ingestion.fundamentals_service import (
    OpenDartFinancialFactsCollector,
    SecCompanyFactsCollector,
)
from asset_frame.ingestion.identifier_service import (
    IdentifierMappingResult,
    RegulatoryIdentifierCollector,
)
from asset_frame.ingestion.krx_batch import KrxMarketBatchService
from asset_frame.ingestion.krx_service import KrxCollector
from asset_frame.ingestion.market_batch import TiingoMarketBatchService, five_year_start
from asset_frame.ingestion.news_service import GdeltNewsCollector
from asset_frame.ingestion.opendart_service import OpenDartDisclosureCollector
from asset_frame.ingestion.service import SecSubmissionsCollector
from asset_frame.ingestion.tiingo_service import TiingoEodCollector
from asset_frame.ingestion.transport import UrllibHttpTransport
from asset_frame.ingestion.universe import load_universe_policy, select_analysis_universe
from asset_frame.sources.registry import load_source_registry
from asset_frame.storage.batch import PostgresBatchRepository
from asset_frame.storage.budget import BYTES_PER_GIB, evaluate_storage_budget, measure_raw_store
from asset_frame.storage.collection_batch import PostgresUniverseCollectionRepository
from asset_frame.storage.krx_batch import PostgresKrxBatchRepository
from asset_frame.storage.migrations import migrate_database
from asset_frame.storage.postgres import PostgresIngestionRepository
from asset_frame.storage.raw import FileRawStore
from asset_frame.storage.universe import PostgresUniverseRepository


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
    sec_facts_parser = subparsers.add_parser(
        "collect-sec-facts", help="collect selected SEC company facts"
    )
    sec_facts_parser.add_argument("--cik", required=True)
    sec_facts_parser.add_argument("--asset-id", required=True, type=UUID)
    sec_facts_parser.add_argument("--raw-store", type=Path, default=Path("var/raw"))
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
    dart_facts_parser = subparsers.add_parser(
        "collect-opendart-facts", help="collect selected OpenDART financial facts"
    )
    dart_facts_parser.add_argument("--corp-code", required=True)
    dart_facts_parser.add_argument("--asset-id", required=True, type=UUID)
    dart_facts_parser.add_argument("--business-year", required=True, type=int)
    dart_facts_parser.add_argument(
        "--report-code", required=True, choices=("11011", "11012", "11013", "11014")
    )
    dart_facts_parser.add_argument("--fs-div", choices=("CFS", "OFS"), default="CFS")
    dart_facts_parser.add_argument("--raw-store", type=Path, default=Path("var/raw"))
    gdelt_parser = subparsers.add_parser(
        "collect-gdelt-news", help="collect recent GDELT article metadata without article bodies"
    )
    gdelt_parser.add_argument("--asset-id", required=True, type=UUID)
    gdelt_parser.add_argument("--query", required=True)
    gdelt_parser.add_argument("--start-at", required=True, type=datetime.fromisoformat)
    gdelt_parser.add_argument("--end-at", required=True, type=datetime.fromisoformat)
    gdelt_parser.add_argument("--max-records", type=int, default=75)
    gdelt_parser.add_argument("--raw-store", type=Path, default=Path("var/raw"))
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
    universe_parser = subparsers.add_parser(
        "build-universe", help="select the reproducible KR or US analysis universe"
    )
    universe_parser.add_argument("--country", required=True, choices=("KR", "US"))
    universe_parser.add_argument("--as-of", required=True, type=date.fromisoformat)
    universe_parser.add_argument(
        "--config", type=Path, default=Path("config/analysis-universe.toml")
    )
    universe_parser.add_argument("--manifest", type=Path, default=Path("config/data-spike.toml"))
    budget_parser = subparsers.add_parser(
        "data-budget-status",
        help="show raw and PostgreSQL storage usage without blocking collection",
    )
    budget_parser.add_argument("--raw-store", type=Path, default=Path("var/raw"))
    budget_parser.add_argument("--config", type=Path, default=Path("config/analysis-universe.toml"))
    discovery_parser = subparsers.add_parser(
        "prepare-tiingo-discovery",
        help="prepare resumable liquidity discovery for active US tickers",
    )
    discovery_parser.add_argument("--as-of", required=True, type=date.fromisoformat)
    discovery_parser.add_argument("--lookback-days", type=int, default=90)
    discovery_parser.add_argument("--raw-store", type=Path, default=Path("var/raw"))
    backfill_parser = subparsers.add_parser(
        "prepare-tiingo-backfill",
        help="prepare a resumable five-year job for the latest US analysis universe",
    )
    backfill_parser.add_argument("--as-of", required=True, type=date.fromisoformat)
    backfill_parser.add_argument("--start-date", type=date.fromisoformat)
    backfill_parser.add_argument("--raw-store", type=Path, default=Path("var/raw"))
    batch_parser = subparsers.add_parser(
        "run-tiingo-job", help="run a bounded number of items from a prepared Tiingo job"
    )
    batch_parser.add_argument("--job-id", required=True, type=UUID)
    batch_parser.add_argument("--max-items", type=int, default=100)
    batch_parser.add_argument("--retry-failed", action="store_true")
    batch_parser.add_argument("--raw-store", type=Path, default=Path("var/raw"))
    job_status_parser = subparsers.add_parser(
        "market-job-status", help="show progress for a resumable market data job"
    )
    job_status_parser.add_argument("--job-id", required=True, type=UUID)
    krx_backfill_parser = subparsers.add_parser(
        "prepare-krx-backfill",
        help="prepare a resumable five-year KRX price backfill",
    )
    krx_backfill_parser.add_argument("--as-of", required=True, type=date.fromisoformat)
    krx_backfill_parser.add_argument("--start-date", type=date.fromisoformat)
    krx_backfill_parser.add_argument("--raw-store", type=Path, default=Path("var/raw"))
    krx_run_parser = subparsers.add_parser(
        "run-krx-job", help="run a bounded number of dates and markets from a KRX job"
    )
    krx_run_parser.add_argument("--job-id", required=True, type=UUID)
    krx_run_parser.add_argument("--max-items", type=int, default=30)
    krx_run_parser.add_argument("--retry-failed", action="store_true")
    krx_run_parser.add_argument("--raw-store", type=Path, default=Path("var/raw"))
    krx_status_parser = subparsers.add_parser(
        "krx-job-status", help="show progress for a resumable KRX backfill job"
    )
    krx_status_parser.add_argument("--job-id", required=True, type=UUID)
    subparsers.add_parser(
        "environment-status", help="show required configuration without exposing values"
    )
    migrate_parser = subparsers.add_parser(
        "migrate-database", help="apply numbered SQL migrations without replacing existing data"
    )
    migrate_parser.add_argument("--migrations", type=Path, default=Path("db/init"))
    prepare_collection_parser = subparsers.add_parser(
        "prepare-universe-collection",
        help="prepare resumable fundamentals or recent-news collection for a universe",
    )
    prepare_collection_parser.add_argument(
        "--kind",
        required=True,
        choices=("sec-fundamentals", "opendart-fundamentals", "gdelt-news"),
    )
    prepare_collection_parser.add_argument("--country", required=True, choices=("KR", "US"))
    prepare_collection_parser.add_argument("--as-of", required=True, type=date.fromisoformat)
    prepare_collection_parser.add_argument("--start-date", type=date.fromisoformat)
    prepare_collection_parser.add_argument("--end-date", type=date.fromisoformat)
    prepare_collection_parser.add_argument("--max-news-records", type=int, default=75)
    prepare_collection_parser.add_argument("--raw-store", type=Path, default=Path("var/raw"))
    run_collection_parser = subparsers.add_parser(
        "run-universe-collection",
        help="run a bounded number of assets from a universe collection job",
    )
    run_collection_parser.add_argument("--job-id", required=True, type=UUID)
    run_collection_parser.add_argument("--max-items", type=int, default=10)
    run_collection_parser.add_argument("--retry-failed", action="store_true")
    run_collection_parser.add_argument("--raw-store", type=Path, default=Path("var/raw"))
    collection_status_parser = subparsers.add_parser(
        "universe-collection-status", help="show universe collection job progress"
    )
    collection_status_parser.add_argument("--job-id", required=True, type=UUID)
    arguments = parser.parse_args()

    if arguments.command == "collect-sec":
        _collect_sec(arguments.cik, arguments.asset_id, arguments.raw_store)
    elif arguments.command == "collect-sec-identifiers":
        _collect_sec_identifiers(arguments.raw_store)
    elif arguments.command == "collect-sec-facts":
        _collect_sec_facts(arguments.cik, arguments.asset_id, arguments.raw_store)
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
    elif arguments.command == "collect-opendart-facts":
        _collect_opendart_facts(
            arguments.corp_code,
            arguments.asset_id,
            arguments.business_year,
            arguments.report_code,
            arguments.fs_div,
            arguments.raw_store,
        )
    elif arguments.command == "collect-gdelt-news":
        _collect_gdelt_news(
            arguments.asset_id,
            arguments.query,
            arguments.start_at,
            arguments.end_at,
            arguments.max_records,
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
    elif arguments.command == "source-status":
        _show_source_status(
            arguments.source_id,
            arguments.data_kind,
            arguments.max_age_hours,
        )
    elif arguments.command == "data-spike-status":
        _show_data_spike_status(arguments.manifest)
    elif arguments.command == "build-universe":
        _build_universe(
            arguments.country,
            arguments.as_of,
            arguments.config,
            arguments.manifest,
        )
    elif arguments.command == "data-budget-status":
        _show_data_budget_status(arguments.raw_store, arguments.config)
    elif arguments.command == "prepare-tiingo-discovery":
        _prepare_tiingo_discovery(arguments.as_of, arguments.lookback_days, arguments.raw_store)
    elif arguments.command == "prepare-tiingo-backfill":
        _prepare_tiingo_backfill(arguments.as_of, arguments.start_date, arguments.raw_store)
    elif arguments.command == "run-tiingo-job":
        _run_tiingo_job(
            arguments.job_id,
            arguments.max_items,
            arguments.retry_failed,
            arguments.raw_store,
        )
    elif arguments.command == "market-job-status":
        _show_market_job_status(arguments.job_id)
    elif arguments.command == "prepare-krx-backfill":
        _prepare_krx_backfill(arguments.as_of, arguments.start_date, arguments.raw_store)
    elif arguments.command == "run-krx-job":
        _run_krx_job(
            arguments.job_id,
            arguments.max_items,
            arguments.retry_failed,
            arguments.raw_store,
        )
    elif arguments.command == "krx-job-status":
        _show_krx_job_status(arguments.job_id)
    elif arguments.command == "environment-status":
        _show_environment_status()
    elif arguments.command == "migrate-database":
        _migrate_database(arguments.migrations)
    elif arguments.command == "prepare-universe-collection":
        _prepare_universe_collection(
            arguments.kind,
            arguments.country,
            arguments.as_of,
            arguments.start_date,
            arguments.end_date,
            arguments.max_news_records,
            arguments.raw_store,
        )
    elif arguments.command == "run-universe-collection":
        _run_universe_collection(
            arguments.job_id,
            arguments.max_items,
            arguments.retry_failed,
            arguments.raw_store,
        )
    elif arguments.command == "universe-collection-status":
        _show_universe_collection_status(arguments.job_id)


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


def _collect_sec_facts(cik: str, asset_id: UUID, raw_store_path: Path) -> None:
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

    facts = SecCompanyFactsCollector(
        source=source,
        transport=UrllibHttpTransport(),
        raw_store=FileRawStore(raw_store_path),
        repository=PostgresIngestionRepository(connection_factory),
    ).collect(cik=cik, asset_id=asset_id, user_agent=user_agent)
    print(f"collected {len(facts)} selected SEC financial facts for asset {asset_id}")


def _collect_opendart_facts(
    corp_code: str,
    asset_id: UUID,
    business_year: int,
    report_code: str,
    fs_div: str,
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

    facts = OpenDartFinancialFactsCollector(
        source=source,
        transport=UrllibHttpTransport(),
        raw_store=FileRawStore(raw_store_path),
        repository=PostgresIngestionRepository(connection_factory),
    ).collect(
        api_key=api_key,
        corp_code=corp_code,
        asset_id=asset_id,
        business_year=business_year,
        report_code=report_code,
        fs_div=fs_div,
    )
    print(f"collected {len(facts)} selected OpenDART financial facts for asset {asset_id}")


def _collect_gdelt_news(
    asset_id: UUID,
    query: str,
    start_at: datetime,
    end_at: datetime,
    max_records: int,
    raw_store_path: Path,
) -> None:
    database_url = _required_environment("DATABASE_URL")
    source = next(
        source
        for source in load_source_registry(Path("config/sources.toml"))
        if source.id == "gdelt-doc"
    )

    @contextmanager
    def connection_factory():  # type: ignore[no-untyped-def]
        with psycopg.connect(database_url) as connection:
            yield connection

    mentions = GdeltNewsCollector(
        source=source,
        transport=UrllibHttpTransport(),
        raw_store=FileRawStore(raw_store_path),
        repository=PostgresIngestionRepository(connection_factory),
    ).collect(
        asset_id=asset_id,
        query=query,
        start_at=start_at,
        end_at=end_at,
        max_records=max_records,
    )
    print(f"collected {len(mentions)} GDELT news metadata rows for asset {asset_id}")


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


def _build_universe(
    country_code: str,
    as_of_date: date,
    config_path: Path,
    manifest_path: Path,
) -> None:
    database_url = _required_environment("DATABASE_URL")
    policy = load_universe_policy(config_path)
    pinned_tickers = frozenset(
        asset.ticker.upper()
        for asset in load_data_spike_manifest(manifest_path)
        if asset.country_code == country_code
    )

    @contextmanager
    def connection_factory():  # type: ignore[no-untyped-def]
        with psycopg.connect(database_url) as connection:
            yield connection

    repository = PostgresUniverseRepository(connection_factory)
    candidates = repository.liquidity_candidates(
        country_code=country_code,
        as_of_date=as_of_date,
        lookback_observations=policy.lookback_observations,
        pinned_tickers=pinned_tickers,
    )
    selection = select_analysis_universe(
        country_code=country_code,
        as_of_date=as_of_date,
        candidates=candidates,
        policy=policy,
    )
    run_id = repository.save_selection(selection, policy)
    equities = sum(item.asset_type.value == "equity" for item in selection.memberships)
    etfs = sum(item.asset_type.value == "etf" for item in selection.memberships)
    print(
        f"analysis universe run={run_id} country={country_code} "
        f"equities={equities}/{policy.equity_limit} etfs={etfs}/{policy.etf_limit} "
        f"input_hash={selection.input_hash}"
    )


def _show_data_budget_status(raw_store_path: Path, config_path: Path) -> None:
    policy = load_universe_policy(config_path)
    database_bytes: int | None = None
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT pg_database_size(current_database())")
            row = cursor.fetchone()
            database_bytes = int(row[0]) if row is not None else None
    status = evaluate_storage_budget(
        raw_store_bytes=measure_raw_store(raw_store_path),
        database_bytes=database_bytes,
        warning_gb=policy.storage_warning_gb,
    )
    raw_gb = Decimal(status.raw_store_bytes) / BYTES_PER_GIB
    database_gb = (
        Decimal(status.database_bytes) / BYTES_PER_GIB
        if status.database_bytes is not None
        else None
    )
    total_gb = Decimal(status.total_bytes) / BYTES_PER_GIB
    database_text = f"{database_gb:.2f}" if database_gb is not None else "unknown"
    print(
        f"raw_gb={raw_gb:.2f} database_gb={database_text} total_gb={total_gb:.2f} "
        f"warning_threshold_gb={policy.storage_warning_gb} "
        f"warning={str(status.warning).lower()} collection_blocked=false"
    )


def _tiingo_batch_service(*, database_url: str, raw_store_path: Path) -> TiingoMarketBatchService:
    source = next(
        source
        for source in load_source_registry(Path("config/sources.toml"))
        if source.id == "tiingo-eod"
    )

    @contextmanager
    def connection_factory():  # type: ignore[no-untyped-def]
        with psycopg.connect(database_url) as connection:
            yield connection

    return TiingoMarketBatchService(
        source=source,
        transport=UrllibHttpTransport(),
        raw_store=FileRawStore(raw_store_path),
        ingestion_repository=PostgresIngestionRepository(connection_factory),
        batch_repository=PostgresBatchRepository(connection_factory),
        universe_repository=PostgresUniverseRepository(connection_factory),
    )


def _prepare_tiingo_discovery(as_of_date: date, lookback_days: int, raw_store_path: Path) -> None:
    if lookback_days <= 0:
        raise SystemExit("--lookback-days must be positive")
    database_url = _required_environment("DATABASE_URL")
    service = _tiingo_batch_service(database_url=database_url, raw_store_path=raw_store_path)
    job_id = service.prepare_discovery(
        as_of_date=as_of_date,
        start_date=as_of_date - timedelta(days=lookback_days),
        end_date=as_of_date,
    )
    print(f"prepared Tiingo liquidity discovery job={job_id} as_of={as_of_date}")


def _run_tiingo_job(
    job_id: UUID,
    max_items: int,
    retry_failed: bool,
    raw_store_path: Path,
) -> None:
    if max_items <= 0:
        raise SystemExit("--max-items must be positive")
    database_url = _required_environment("DATABASE_URL")
    api_key = _required_environment("TIINGO_API_KEY")
    service = _tiingo_batch_service(database_url=database_url, raw_store_path=raw_store_path)
    result = service.run(
        job_id=job_id,
        api_key=api_key,
        max_items=max_items,
        retry_failed=retry_failed,
    )
    print(
        f"Tiingo job={job_id} attempted={result.attempted} succeeded={result.succeeded} "
        f"failed={result.failed} records_accepted={result.records_accepted}"
    )


def _prepare_tiingo_backfill(
    as_of_date: date, start_date: date | None, raw_store_path: Path
) -> None:
    selected_start = start_date or five_year_start(as_of_date)
    if selected_start > as_of_date:
        raise SystemExit("--start-date must not be after --as-of")
    database_url = _required_environment("DATABASE_URL")
    service = _tiingo_batch_service(database_url=database_url, raw_store_path=raw_store_path)
    job_id = service.prepare_universe_backfill(
        as_of_date=as_of_date,
        start_date=selected_start,
        end_date=as_of_date,
    )
    print(f"prepared Tiingo universe backfill job={job_id} start={selected_start} end={as_of_date}")


def _show_market_job_status(job_id: UUID) -> None:
    database_url = _required_environment("DATABASE_URL")

    @contextmanager
    def connection_factory():  # type: ignore[no-untyped-def]
        with psycopg.connect(database_url) as connection:
            yield connection

    progress = PostgresBatchRepository(connection_factory).job_progress(job_id)
    print(
        f"job={job_id} type={progress.job.job_type} status={progress.job.status} "
        f"total={progress.total} pending={progress.pending} running={progress.running} "
        f"succeeded={progress.succeeded} failed={progress.failed}"
    )


def _krx_batch_service(*, database_url: str, raw_store_path: Path) -> KrxMarketBatchService:
    source = next(
        source
        for source in load_source_registry(Path("config/sources.toml"))
        if source.id == "krx-open-api"
    )

    @contextmanager
    def connection_factory():  # type: ignore[no-untyped-def]
        with psycopg.connect(database_url) as connection:
            yield connection

    ingestion_repository = PostgresIngestionRepository(connection_factory)
    collector = KrxCollector(
        source=source,
        transport=UrllibHttpTransport(),
        raw_store=FileRawStore(raw_store_path),
        repository=ingestion_repository,
    )
    return KrxMarketBatchService(
        source=source,
        collector=collector,
        ingestion_repository=ingestion_repository,
        batch_repository=PostgresKrxBatchRepository(connection_factory),
    )


def _prepare_krx_backfill(as_of_date: date, start_date: date | None, raw_store_path: Path) -> None:
    selected_start = start_date or five_year_start(as_of_date)
    if selected_start > as_of_date:
        raise SystemExit("--start-date must not be after --as-of")
    database_url = _required_environment("DATABASE_URL")
    service = _krx_batch_service(database_url=database_url, raw_store_path=raw_store_path)
    job_id = service.prepare(
        as_of_date=as_of_date,
        start_date=selected_start,
        end_date=as_of_date,
    )
    print(f"prepared KRX backfill job={job_id} start={selected_start} end={as_of_date}")


def _run_krx_job(
    job_id: UUID,
    max_items: int,
    retry_failed: bool,
    raw_store_path: Path,
) -> None:
    if max_items <= 0:
        raise SystemExit("--max-items must be positive")
    database_url = _required_environment("DATABASE_URL")
    api_key = _required_environment("KRX_API_KEY")
    service = _krx_batch_service(database_url=database_url, raw_store_path=raw_store_path)
    result = service.run(
        job_id=job_id,
        api_key=api_key,
        max_items=max_items,
        retry_failed=retry_failed,
    )
    print(
        f"KRX job={job_id} attempted={result.attempted} succeeded={result.succeeded} "
        f"no_data={result.no_data} failed={result.failed} "
        f"records_accepted={result.records_accepted}"
    )


def _show_krx_job_status(job_id: UUID) -> None:
    database_url = _required_environment("DATABASE_URL")

    @contextmanager
    def connection_factory():  # type: ignore[no-untyped-def]
        with psycopg.connect(database_url) as connection:
            yield connection

    progress = PostgresKrxBatchRepository(connection_factory).job_progress(job_id)
    print(
        f"job={job_id} status={progress.job.status} total={progress.total} "
        f"pending={progress.pending} running={progress.running} "
        f"succeeded={progress.succeeded} no_data={progress.no_data} failed={progress.failed}"
    )


def _show_environment_status() -> None:
    for requirement in ENVIRONMENT_REQUIREMENTS:
        names = "+".join(requirement.names)
        configured = str(requirement.configured()).lower()
        print(
            f"variables={names} phase={requirement.phase} configured={configured} "
            f"capability={requirement.capability}"
        )
    print(
        "variables=GDELT phase=current configured=not_required "
        "capability=recent global news metadata"
    )


def _migrate_database(migrations_path: Path) -> None:
    database_url = _required_environment("DATABASE_URL")
    result = migrate_database(database_url, migrations_path)
    print(
        f"database migrations applied={len(result.applied)} "
        f"baselined={len(result.baselined)} already_applied={len(result.already_applied)}"
    )
    if result.applied:
        print(f"applied: {', '.join(result.applied)}")
    if result.baselined:
        print(f"baselined existing schema: {', '.join(result.baselined)}")


def _available_collection_service(
    *, database_url: str, raw_store_path: Path
) -> AvailableUniverseCollectionService:
    sources = {source.id: source for source in load_source_registry(Path("config/sources.toml"))}

    @contextmanager
    def connection_factory():  # type: ignore[no-untyped-def]
        with psycopg.connect(database_url) as connection:
            yield connection

    repository = PostgresIngestionRepository(connection_factory)
    transport = UrllibHttpTransport()
    raw_store = FileRawStore(raw_store_path)
    return AvailableUniverseCollectionService(
        ingestion_repository=repository,
        universe_repository=PostgresUniverseRepository(connection_factory),
        batch_repository=PostgresUniverseCollectionRepository(connection_factory),
        sec_filings=SecSubmissionsCollector(
            source=sources["sec-edgar-submissions"],
            transport=transport,
            raw_store=raw_store,
            repository=repository,
        ),
        sec_facts=SecCompanyFactsCollector(
            source=sources["sec-edgar-submissions"],
            transport=transport,
            raw_store=raw_store,
            repository=repository,
        ),
        opendart_filings=OpenDartDisclosureCollector(
            source=sources["opendart"],
            transport=transport,
            raw_store=raw_store,
            repository=repository,
        ),
        opendart_facts=OpenDartFinancialFactsCollector(
            source=sources["opendart"],
            transport=transport,
            raw_store=raw_store,
            repository=repository,
        ),
        gdelt_news=GdeltNewsCollector(
            source=sources["gdelt-doc"],
            transport=transport,
            raw_store=raw_store,
            repository=repository,
        ),
    )


def _prepare_universe_collection(
    kind: str,
    country_code: str,
    as_of_date: date,
    start_date: date | None,
    end_date: date | None,
    max_news_records: int,
    raw_store_path: Path,
) -> None:
    job_type = kind.replace("-", "_")
    selected_end = end_date or as_of_date
    selected_start = start_date or (
        selected_end - timedelta(days=30)
        if job_type == "gdelt_news"
        else five_year_start(selected_end)
    )
    if selected_start > selected_end:
        raise SystemExit("--start-date must not be after --end-date/--as-of")
    if job_type == "gdelt_news" and max_news_records not in range(1, 251):
        raise SystemExit("--max-news-records must be between 1 and 250")
    database_url = _required_environment("DATABASE_URL")
    service = _available_collection_service(
        database_url=database_url, raw_store_path=raw_store_path
    )
    job_id = service.prepare(
        job_type=job_type,
        country_code=country_code,
        as_of_date=as_of_date,
        start_date=selected_start,
        end_date=selected_end,
        max_news_records=max_news_records,
    )
    print(
        f"prepared universe collection job={job_id} type={job_type} country={country_code} "
        f"start={selected_start} end={selected_end}"
    )


def _run_universe_collection(
    job_id: UUID, max_items: int, retry_failed: bool, raw_store_path: Path
) -> None:
    if max_items <= 0:
        raise SystemExit("--max-items must be positive")
    database_url = _required_environment("DATABASE_URL")

    @contextmanager
    def connection_factory():  # type: ignore[no-untyped-def]
        with psycopg.connect(database_url) as connection:
            yield connection

    job = PostgresUniverseCollectionRepository(connection_factory).get_job(job_id)
    sec_user_agent = (
        _required_environment("SEC_USER_AGENT") if job.job_type == "sec_fundamentals" else None
    )
    opendart_api_key = (
        _required_environment("OPENDART_API_KEY")
        if job.job_type == "opendart_fundamentals"
        else None
    )
    service = _available_collection_service(
        database_url=database_url, raw_store_path=raw_store_path
    )
    result = service.run(
        job_id=job_id,
        max_items=max_items,
        retry_failed=retry_failed,
        sec_user_agent=sec_user_agent,
        opendart_api_key=opendart_api_key,
    )
    print(
        f"universe collection job={job_id} attempted={result.attempted} "
        f"succeeded={result.succeeded} no_data={result.no_data} failed={result.failed} "
        f"records_accepted={result.records_accepted}"
    )


def _show_universe_collection_status(job_id: UUID) -> None:
    database_url = _required_environment("DATABASE_URL")

    @contextmanager
    def connection_factory():  # type: ignore[no-untyped-def]
        with psycopg.connect(database_url) as connection:
            yield connection

    progress = PostgresUniverseCollectionRepository(connection_factory).job_progress(job_id)
    print(
        f"job={job_id} type={progress.job.job_type} status={progress.job.status} "
        f"total={progress.total} pending={progress.pending} running={progress.running} "
        f"succeeded={progress.succeeded} no_data={progress.no_data} failed={progress.failed}"
    )

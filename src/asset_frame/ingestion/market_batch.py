from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from asset_frame.connectors.tiingo import TIINGO_SOURCE_ID, tiingo_asset_id
from asset_frame.connectors.tiingo_universe import (
    build_supported_tickers_request,
    eligible_us_tickers,
    parse_supported_tickers,
)
from asset_frame.domain.models import (
    Asset,
    AssetIdentifier,
    DataKind,
    IdentifierType,
    ImplementationStatus,
    SourceDefinition,
)
from asset_frame.ingestion.retention import years_before
from asset_frame.ingestion.run import IngestionRunSession
from asset_frame.ingestion.tiingo_service import TiingoEodCollector
from asset_frame.ingestion.transport import HttpTransport
from asset_frame.storage.batch import MarketDataJobItem, PostgresBatchRepository
from asset_frame.storage.raw import RawStore
from asset_frame.storage.repository import IngestionRepository
from asset_frame.storage.universe import PostgresUniverseRepository
from asset_frame.storage.universe_v2 import PostgresUniverseV2Repository


@dataclass(frozen=True, slots=True)
class MarketBatchResult:
    attempted: int
    succeeded: int
    failed: int
    records_accepted: int


class TiingoMarketBatchService:
    def __init__(
        self,
        *,
        source: SourceDefinition,
        transport: HttpTransport,
        raw_store: RawStore,
        ingestion_repository: IngestionRepository,
        batch_repository: PostgresBatchRepository,
        universe_repository: PostgresUniverseRepository | None = None,
        symbol_budget_repository: PostgresUniverseV2Repository | None = None,
        monthly_unique_symbol_limit: int = 400,
    ) -> None:
        if source.id != TIINGO_SOURCE_ID:
            raise ValueError("Tiingo batch service requires the Tiingo EOD source definition")
        if not source.enabled or source.implementation_status is not ImplementationStatus.AVAILABLE:
            raise ValueError("Tiingo EOD source is not available and enabled")
        self._source = source
        self._transport = transport
        self._raw_store = raw_store
        self._ingestion_repository = ingestion_repository
        self._batch_repository = batch_repository
        self._universe_repository = universe_repository
        self._symbol_budget_repository = symbol_budget_repository
        if monthly_unique_symbol_limit <= 0:
            raise ValueError("monthly_unique_symbol_limit must be positive")
        self._monthly_unique_symbol_limit = monthly_unique_symbol_limit

    def prepare_discovery(
        self,
        *,
        as_of_date: date,
        start_date: date,
        end_date: date,
    ) -> UUID:
        self._ingestion_repository.upsert_source(self._source)
        with IngestionRunSession(
            self._ingestion_repository,
            source_id=self._source.id,
            data_kind=DataKind.ASSET_IDENTIFIER.value,
        ) as run:
            request = build_supported_tickers_request()
            response = self._transport.fetch(request)
            if response.status_code != 200:
                raise RuntimeError(
                    f"Tiingo supported ticker list returned HTTP {response.status_code}"
                )
            snapshot = self._raw_store.save(
                snapshot_id=uuid4(),
                source_id=self._source.id,
                request_url=request.url,
                response=response,
                ingestion_run_id=run.id,
            )
            self._ingestion_repository.save_raw_snapshot(snapshot)
            eligible = eligible_us_tickers(
                parse_supported_tickers(response.body), as_of_date=as_of_date
            )
            existing_asset_ids = {
                asset.id for asset in self._ingestion_repository.list_assets(country_code="US")
            }
            assets = tuple(
                Asset(
                    id=tiingo_asset_id(item.ticker),
                    name=item.ticker,
                    asset_type=item.asset_type,
                    country_code="US",
                    currency="USD",
                )
                for item in eligible
                if item.asset_type is not None
                and tiingo_asset_id(item.ticker) not in existing_asset_ids
            )
            identifiers = tuple(
                identifier
                for item in eligible
                for identifier in (
                    AssetIdentifier(
                        tiingo_asset_id(item.ticker), IdentifierType.TICKER, item.ticker
                    ),
                    AssetIdentifier(
                        tiingo_asset_id(item.ticker),
                        IdentifierType.EXCHANGE_CODE,
                        item.exchange,
                    ),
                )
            )
            self._ingestion_repository.upsert_assets(assets, identifiers)
            job_id = self._batch_repository.prepare_job(
                source_id=self._source.id,
                job_type="liquidity_discovery",
                country_code="US",
                as_of_date=as_of_date,
                start_date=start_date,
                end_date=end_date,
                items=tuple(
                    MarketDataJobItem(
                        ticker=item.ticker,
                        asset_type=item.asset_type,
                        exchange_code=item.exchange,
                    )
                    for item in eligible
                    if item.asset_type is not None
                ),
            )
            run.succeed(records_received=len(eligible), records_accepted=len(eligible))
            return job_id

    def prepare_universe_backfill(
        self,
        *,
        as_of_date: date,
        start_date: date,
        end_date: date,
    ) -> UUID:
        if start_date < years_before(end_date, 10):
            raise ValueError("price backfill window must not exceed 10 years")
        if self._universe_repository is None:
            raise RuntimeError("universe repository is required to prepare a backfill")
        memberships = self._universe_repository.latest_memberships(
            country_code="US", as_of_date=as_of_date
        )
        if not memberships:
            raise RuntimeError("no US analysis universe is available for the requested date")
        self._ingestion_repository.upsert_source(self._source)
        return self._batch_repository.prepare_job(
            source_id=self._source.id,
            job_type="universe_backfill",
            country_code="US",
            as_of_date=as_of_date,
            start_date=start_date,
            end_date=end_date,
            items=tuple(
                MarketDataJobItem(ticker=item.ticker, asset_type=item.asset_type)
                for item in memberships
            ),
        )

    def run(
        self,
        *,
        job_id: UUID,
        api_key: str,
        max_items: int,
        retry_failed: bool,
    ) -> MarketBatchResult:
        if max_items <= 0:
            raise ValueError("max_items must be positive")
        job = self._batch_repository.get_job(job_id)
        if job.source_id != self._source.id or job.country_code != "US":
            raise ValueError("market data job is not a Tiingo US job")
        items = self._batch_repository.claim_items(
            job_id=job_id, limit=max_items, retry_failed=retry_failed
        )
        collector = TiingoEodCollector(
            source=self._source,
            transport=self._transport,
            raw_store=self._raw_store,
            repository=self._ingestion_repository,
        )
        succeeded = 0
        failed = 0
        records_accepted = 0
        for item in items:
            if self._symbol_budget_repository is not None:
                reservation = self._symbol_budget_repository.reserve_monthly_symbol(
                    source_id=self._source.id,
                    symbol=item.ticker,
                    used_at=datetime.now(UTC),
                    unique_symbol_limit=self._monthly_unique_symbol_limit,
                )
                if not reservation.accepted:
                    self._batch_repository.fail_item(
                        job_id=job_id,
                        ticker=item.ticker,
                        error_message=(
                            "Tiingo monthly unique symbol limit reached: "
                            f"{reservation.unique_symbol_count}/"
                            f"{reservation.unique_symbol_limit}"
                        ),
                    )
                    failed += 1
                    continue
            try:
                result = collector.collect(
                    ticker=item.ticker,
                    asset_type=item.asset_type,
                    api_key=api_key,
                    start_date=job.start_date,
                    end_date=job.end_date,
                    include_corporate_actions=job.job_type != "liquidity_discovery",
                )
            except Exception as error:  # noqa: BLE001 - item failures must not abort the batch
                self._batch_repository.fail_item(
                    job_id=job_id,
                    ticker=item.ticker,
                    error_message=f"{type(error).__name__}: {error}",
                )
                failed += 1
                continue
            self._batch_repository.complete_item(
                job_id=job_id,
                ticker=item.ticker,
                records_accepted=result.accepted_prices,
            )
            succeeded += 1
            records_accepted += result.accepted_prices
        self._batch_repository.refresh_job_status(job_id)
        return MarketBatchResult(len(items), succeeded, failed, records_accepted)


def ten_year_start(as_of_date: date) -> date:
    return years_before(as_of_date, 10)

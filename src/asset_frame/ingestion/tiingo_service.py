from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import uuid4

from asset_frame.connectors.tiingo import (
    TIINGO_SOURCE_ID,
    build_metadata_request,
    build_prices_request,
    parse_metadata,
    parse_prices,
)
from asset_frame.domain.models import (
    Asset,
    AssetType,
    ImplementationStatus,
    QuarantinedPrice,
    SourceDefinition,
)
from asset_frame.ingestion.transport import HttpTransport
from asset_frame.quality.prices import validate_prices
from asset_frame.storage.raw import RawStore
from asset_frame.storage.repository import IngestionRepository


@dataclass(frozen=True, slots=True)
class TiingoCollectionResult:
    asset: Asset
    accepted_prices: int
    quarantined_prices: int
    corporate_actions: int


class TiingoEodCollector:
    def __init__(
        self,
        *,
        source: SourceDefinition,
        transport: HttpTransport,
        raw_store: RawStore,
        repository: IngestionRepository,
    ) -> None:
        if source.id != TIINGO_SOURCE_ID:
            raise ValueError("Tiingo collector requires the Tiingo EOD source definition")
        if not source.enabled or source.implementation_status is not ImplementationStatus.AVAILABLE:
            raise ValueError("Tiingo EOD source is not available and enabled")
        self._source = source
        self._transport = transport
        self._raw_store = raw_store
        self._repository = repository

    def collect(
        self,
        *,
        ticker: str,
        asset_type: AssetType,
        api_key: str,
        start_date: date,
        end_date: date,
    ) -> TiingoCollectionResult:
        self._repository.upsert_source(self._source)
        metadata_request = build_metadata_request(ticker, api_key)
        metadata_response = self._transport.fetch(metadata_request)
        if metadata_response.status_code != 200:
            raise RuntimeError(f"Tiingo metadata returned HTTP {metadata_response.status_code}")
        metadata_snapshot = self._raw_store.save(
            snapshot_id=uuid4(),
            source_id=self._source.id,
            request_url=metadata_request.url,
            response=metadata_response,
        )
        self._repository.save_raw_snapshot(metadata_snapshot)
        parsed_asset = parse_metadata(
            metadata_response.body,
            expected_ticker=ticker,
            asset_type=asset_type,
        )
        self._repository.upsert_assets((parsed_asset.asset,), parsed_asset.identifiers)

        prices_request = build_prices_request(
            ticker,
            api_key=api_key,
            start_date=start_date,
            end_date=end_date,
        )
        prices_response = self._transport.fetch(prices_request)
        if prices_response.status_code != 200:
            raise RuntimeError(f"Tiingo prices returned HTTP {prices_response.status_code}")
        prices_snapshot = self._raw_store.save(
            snapshot_id=uuid4(),
            source_id=self._source.id,
            request_url=prices_request.url,
            response=prices_response,
        )
        self._repository.save_raw_snapshot(prices_snapshot)
        parsed_prices = parse_prices(
            prices_response.body,
            asset_id=parsed_asset.asset.id,
            snapshot=prices_snapshot,
            start_date=start_date,
            end_date=end_date,
        )

        validation = validate_prices(parsed_prices.prices)
        issues_by_date: dict[date, list[dict[str, str]]] = {}
        global_issues: list[dict[str, str]] = []
        for issue in validation.issues:
            details = {"code": issue.code, "message": issue.message}
            if issue.trading_date is None:
                global_issues.append(details)
            else:
                issues_by_date.setdefault(issue.trading_date, []).append(details)

        accepted = []
        quarantined = []
        for price in parsed_prices.prices:
            issues = [*global_issues, *issues_by_date.get(price.trading_date, [])]
            if issues:
                quarantined.append(
                    QuarantinedPrice(
                        price=price,
                        issue_code=issues[0]["code"],
                        details={"issues": issues, "trading_date": str(price.trading_date)},
                    )
                )
            else:
                accepted.append(price)

        accepted_dates = {price.trading_date for price in accepted}
        accepted_actions = tuple(
            action
            for action in parsed_prices.corporate_actions
            if action.effective_at in accepted_dates
        )
        self._repository.save_prices(tuple(accepted))
        self._repository.save_corporate_actions(accepted_actions)
        self._repository.save_quarantined_prices(tuple(quarantined))
        return TiingoCollectionResult(
            asset=parsed_asset.asset,
            accepted_prices=len(accepted),
            quarantined_prices=len(quarantined),
            corporate_actions=len(accepted_actions),
        )

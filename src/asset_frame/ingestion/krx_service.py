from __future__ import annotations

from collections import Counter
from datetime import date
from uuid import uuid4

from asset_frame.connectors.krx import KrxDataset, build_request, parse_assets, parse_prices
from asset_frame.domain.models import (
    AssetType,
    ImplementationStatus,
    QuarantinedPrice,
    SourceDefinition,
)
from asset_frame.ingestion.transport import HttpTransport
from asset_frame.quality.prices import validate_prices
from asset_frame.storage.raw import RawStore
from asset_frame.storage.repository import IngestionRepository


class KrxCollector:
    def __init__(
        self,
        *,
        source: SourceDefinition,
        transport: HttpTransport,
        raw_store: RawStore,
        repository: IngestionRepository,
    ) -> None:
        if source.id != "krx-open-api":
            raise ValueError("KRX collector requires the KRX source definition")
        if not source.enabled or source.implementation_status is not ImplementationStatus.AVAILABLE:
            raise ValueError("KRX source is not available and enabled")
        self._source = source
        self._transport = transport
        self._raw_store = raw_store
        self._repository = repository

    def collect(self, *, dataset: KrxDataset, business_date: date, api_key: str) -> int:
        request = build_request(dataset, business_date, api_key)
        response = self._transport.fetch(request)
        if response.status_code != 200:
            raise RuntimeError(f"KRX returned HTTP {response.status_code}")
        snapshot = self._raw_store.save(
            snapshot_id=uuid4(),
            source_id=self._source.id,
            request_url=request.url,
            response=response,
        )
        self._repository.upsert_source(self._source)
        self._repository.save_raw_snapshot(snapshot)

        if dataset in (KrxDataset.KOSPI_ASSETS, KrxDataset.KOSDAQ_ASSETS):
            parsed = parse_assets(response.body)
            self._repository.upsert_assets(parsed.assets, parsed.identifiers)
            return len(parsed.assets)

        asset_type = AssetType.ETF if dataset is KrxDataset.ETF_PRICES else AssetType.EQUITY
        assets, identifiers, prices = parse_prices(
            response.body, snapshot=snapshot, asset_type=asset_type
        )
        key_counts = Counter((price.asset_id, price.trading_date) for price in prices)
        accepted = []
        quarantined = []
        for price in prices:
            quality = validate_prices((price,))
            issues = [{"code": issue.code, "message": issue.message} for issue in quality.issues]
            if price.trading_date != business_date:
                issues.append(
                    {
                        "code": "business_date_mismatch",
                        "message": (
                            f"response date {price.trading_date} does not match "
                            f"requested date {business_date}"
                        ),
                    }
                )
            if key_counts[(price.asset_id, price.trading_date)] > 1:
                issues.append(
                    {
                        "code": "duplicate_asset_date",
                        "message": "duplicate asset and trading date in KRX response",
                    }
                )
            if issues:
                quarantined.append(
                    QuarantinedPrice(
                        price=price,
                        issue_code=issues[0]["code"],
                        details={
                            "issues": issues,
                            "trading_date": str(price.trading_date),
                            "requested_date": str(business_date),
                        },
                    )
                )
            else:
                accepted.append(price)
        self._repository.upsert_assets(assets, identifiers)
        self._repository.save_prices(tuple(accepted))
        self._repository.save_quarantined_prices(tuple(quarantined))
        return len(accepted)

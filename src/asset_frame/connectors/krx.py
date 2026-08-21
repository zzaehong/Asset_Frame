from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from urllib.parse import urlencode
from uuid import NAMESPACE_URL, UUID, uuid5

from asset_frame.domain.models import (
    Asset,
    AssetIdentifier,
    AssetType,
    FetchRequest,
    IdentifierType,
    PriceObservation,
    RawSnapshot,
)

KRX_SOURCE_ID = "krx-open-api"
KRX_API_BASE_URL = "https://data-dbg.krx.co.kr/svc/apis"


class KrxDataset(StrEnum):
    KOSPI_PRICES = "sto/stk_bydd_trd"
    KOSDAQ_PRICES = "sto/ksq_bydd_trd"
    ETF_PRICES = "etp/etf_bydd_trd"
    KOSPI_ASSETS = "sto/stk_isu_base_info"
    KOSDAQ_ASSETS = "sto/ksq_isu_base_info"


class KrxPayloadError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ParsedAssets:
    assets: tuple[Asset, ...]
    identifiers: tuple[AssetIdentifier, ...]


def build_request(dataset: KrxDataset, business_date: date, api_key: str) -> FetchRequest:
    if not api_key.strip():
        raise ValueError("KRX API key is required")
    query = urlencode({"basDd": business_date.strftime("%Y%m%d")})
    return FetchRequest(
        url=f"{KRX_API_BASE_URL}/{dataset.value}?{query}",
        headers={"Accept": "application/json", "AUTH_KEY": api_key},
    )


def parse_assets(body: bytes, *, asset_type: AssetType = AssetType.EQUITY) -> ParsedAssets:
    rows = _rows(body)
    assets: list[Asset] = []
    identifiers: list[AssetIdentifier] = []
    for row in rows:
        ticker = _required(row, "ISU_SRT_CD")
        asset_id = krx_asset_id(ticker)
        assets.append(
            Asset(
                id=asset_id,
                name=_required(row, "ISU_ABBRV"),
                asset_type=asset_type,
                country_code="KR",
                currency="KRW",
            )
        )
        identifiers.extend(
            (
                AssetIdentifier(asset_id, IdentifierType.TICKER, ticker),
                AssetIdentifier(asset_id, IdentifierType.ISIN, _required(row, "ISU_CD")),
                AssetIdentifier(
                    asset_id, IdentifierType.EXCHANGE_CODE, _required(row, "MKT_TP_NM")
                ),
            )
        )
    return ParsedAssets(tuple(assets), tuple(identifiers))


def parse_prices(
    body: bytes,
    *,
    snapshot: RawSnapshot,
    asset_type: AssetType,
) -> tuple[tuple[Asset, ...], tuple[AssetIdentifier, ...], tuple[PriceObservation, ...]]:
    rows = _rows(body)
    assets: list[Asset] = []
    identifiers: list[AssetIdentifier] = []
    prices: list[PriceObservation] = []
    for row in rows:
        ticker = _required(row, "ISU_CD")
        asset_id = krx_asset_id(ticker)
        assets.append(Asset(asset_id, _required(row, "ISU_NM"), asset_type, "KR", "KRW"))
        identifiers.append(AssetIdentifier(asset_id, IdentifierType.TICKER, ticker))
        prices.append(
            PriceObservation(
                asset_id=asset_id,
                source_id=KRX_SOURCE_ID,
                raw_snapshot_id=snapshot.id,
                trading_date=_date(row, "BAS_DD"),
                currency="KRW",
                open=_decimal(row, "TDD_OPNPRC"),
                high=_decimal(row, "TDD_HGPRC"),
                low=_decimal(row, "TDD_LWPRC"),
                close=_required_decimal(row, "TDD_CLSPRC"),
                adjusted_close=None,
                volume=_decimal(row, "ACC_TRDVOL"),
                fetched_at=snapshot.fetched_at,
                price_basis="raw",
            )
        )
    return tuple(assets), tuple(identifiers), tuple(prices)


def krx_asset_id(ticker: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"https://data.krx.co.kr/asset/{ticker}")


def _rows(body: bytes) -> list[dict[str, str]]:
    try:
        payload = json.loads(body)
        rows = payload["OutBlock_1"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise KrxPayloadError("invalid KRX response envelope") from error
    if not isinstance(rows, list):
        raise KrxPayloadError("KRX response rows must be a list")
    return rows


def _required(row: dict[str, str], name: str) -> str:
    value = row.get(name)
    if not isinstance(value, str) or not value:
        raise KrxPayloadError(f"KRX field is missing: {name}")
    return value


def _date(row: dict[str, str], name: str) -> date:
    try:
        return datetime.strptime(_required(row, name), "%Y%m%d").replace(tzinfo=UTC).date()
    except ValueError as error:
        raise KrxPayloadError(f"KRX date is invalid: {name}") from error


def _decimal(row: dict[str, str], name: str) -> Decimal | None:
    value = row.get(name)
    if value in (None, ""):
        return None
    try:
        return Decimal(value.replace(",", ""))
    except (AttributeError, InvalidOperation) as error:
        raise KrxPayloadError(f"KRX number is invalid: {name}") from error


def _required_decimal(row: dict[str, str], name: str) -> Decimal:
    value = _decimal(row, name)
    if value is None:
        raise KrxPayloadError(f"KRX number is missing: {name}")
    return value

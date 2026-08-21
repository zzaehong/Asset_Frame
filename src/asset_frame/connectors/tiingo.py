from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote, urlencode
from uuid import NAMESPACE_URL, UUID, uuid5

from asset_frame.domain.models import (
    Asset,
    AssetIdentifier,
    AssetType,
    CorporateAction,
    FetchRequest,
    IdentifierType,
    PriceObservation,
    RawSnapshot,
)

TIINGO_SOURCE_ID = "tiingo-eod"
TIINGO_DAILY_BASE_URL = "https://api.tiingo.com/tiingo/daily"
_TICKER_PATTERN = re.compile(r"[A-Za-z0-9-]+")


class TiingoPayloadError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ParsedTiingoAsset:
    asset: Asset
    identifiers: tuple[AssetIdentifier, ...]


@dataclass(frozen=True, slots=True)
class ParsedTiingoPrices:
    prices: tuple[PriceObservation, ...]
    corporate_actions: tuple[CorporateAction, ...]


def normalize_ticker(ticker: str) -> str:
    normalized = ticker.strip().upper()
    if not _TICKER_PATTERN.fullmatch(normalized):
        raise ValueError("Tiingo ticker must contain only ASCII letters, digits, or dashes")
    return normalized


def tiingo_asset_id(ticker: str) -> UUID:
    normalized = normalize_ticker(ticker)
    return uuid5(NAMESPACE_URL, f"{TIINGO_DAILY_BASE_URL}/{normalized}")


def build_metadata_request(ticker: str, api_key: str) -> FetchRequest:
    normalized = normalize_ticker(ticker)
    return FetchRequest(
        url=f"{TIINGO_DAILY_BASE_URL}/{quote(normalized, safe='-')}",
        headers=_headers(api_key),
    )


def build_prices_request(
    ticker: str,
    *,
    api_key: str,
    start_date: date,
    end_date: date,
) -> FetchRequest:
    if start_date > end_date:
        raise ValueError("Tiingo start date must not be after end date")
    normalized = normalize_ticker(ticker)
    query = urlencode(
        {
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "format": "json",
            "resampleFreq": "daily",
        }
    )
    return FetchRequest(
        url=f"{TIINGO_DAILY_BASE_URL}/{quote(normalized, safe='-')}/prices?{query}",
        headers=_headers(api_key),
    )


def parse_metadata(
    body: bytes,
    *,
    expected_ticker: str,
    asset_type: AssetType,
) -> ParsedTiingoAsset:
    payload = _json(body)
    if not isinstance(payload, dict):
        raise TiingoPayloadError("Tiingo metadata payload must be an object")
    ticker = normalize_ticker(_required_string(payload, "ticker"))
    if ticker != normalize_ticker(expected_ticker):
        raise TiingoPayloadError("Tiingo metadata ticker does not match request")
    asset_id = tiingo_asset_id(ticker)
    exchange_code = _required_string(payload, "exchangeCode")
    return ParsedTiingoAsset(
        asset=Asset(asset_id, _required_string(payload, "name"), asset_type, "US", "USD"),
        identifiers=(
            AssetIdentifier(asset_id, IdentifierType.TICKER, ticker),
            AssetIdentifier(asset_id, IdentifierType.EXCHANGE_CODE, exchange_code),
        ),
    )


def parse_prices(
    body: bytes,
    *,
    asset_id: UUID,
    snapshot: RawSnapshot,
    start_date: date,
    end_date: date,
) -> ParsedTiingoPrices:
    payload = _json(body)
    if not isinstance(payload, list):
        raise TiingoPayloadError("Tiingo prices payload must be a list")
    prices: list[PriceObservation] = []
    actions: list[CorporateAction] = []
    for row in payload:
        if not isinstance(row, dict):
            raise TiingoPayloadError("Tiingo price row must be an object")
        trading_date = _date(row, "date")
        if not start_date <= trading_date <= end_date:
            raise TiingoPayloadError("Tiingo price date is outside the requested range")
        div_cash = _required_decimal(row, "divCash")
        split_factor = _required_decimal(row, "splitFactor")
        if div_cash < 0:
            raise TiingoPayloadError("Tiingo dividend must not be negative")
        if split_factor <= 0:
            raise TiingoPayloadError("Tiingo split factor must be positive")
        prices.append(
            PriceObservation(
                asset_id=asset_id,
                source_id=TIINGO_SOURCE_ID,
                raw_snapshot_id=snapshot.id,
                trading_date=trading_date,
                currency="USD",
                open=_required_decimal(row, "open"),
                high=_required_decimal(row, "high"),
                low=_required_decimal(row, "low"),
                close=_required_decimal(row, "close"),
                adjusted_close=_required_decimal(row, "adjClose"),
                volume=_required_decimal(row, "volume"),
                fetched_at=snapshot.fetched_at,
                price_basis="raw_with_crsp_adjusted_close",
            )
        )
        if div_cash > 0:
            actions.append(
                CorporateAction(
                    asset_id=asset_id,
                    source_id=TIINGO_SOURCE_ID,
                    raw_snapshot_id=snapshot.id,
                    action_type="cash_dividend",
                    effective_at=trading_date,
                    announced_at=None,
                    amount=div_cash,
                    currency="USD",
                    metadata={"date_basis": "ex_date"},
                )
            )
        if split_factor != 1:
            actions.append(
                CorporateAction(
                    asset_id=asset_id,
                    source_id=TIINGO_SOURCE_ID,
                    raw_snapshot_id=snapshot.id,
                    action_type="split",
                    effective_at=trading_date,
                    announced_at=None,
                    ratio_numerator=split_factor,
                    ratio_denominator=Decimal(1),
                    metadata={"provider_split_factor": str(split_factor)},
                )
            )
    return ParsedTiingoPrices(tuple(prices), tuple(actions))


def _headers(api_key: str) -> dict[str, str]:
    if not api_key.strip():
        raise ValueError("Tiingo API key is required")
    return {"Accept": "application/json", "Authorization": f"Token {api_key}"}


def _json(body: bytes) -> object:
    try:
        return json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise TiingoPayloadError("invalid Tiingo JSON payload") from error


def _required_string(row: dict[str, Any], name: str) -> str:
    value = row.get(name)
    if not isinstance(value, str) or not value:
        raise TiingoPayloadError(f"Tiingo field is missing: {name}")
    return value


def _date(row: dict[str, Any], name: str) -> date:
    value = _required_string(row, name)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError as error:
        raise TiingoPayloadError(f"Tiingo date is invalid: {name}") from error


def _required_decimal(row: dict[str, Any], name: str) -> Decimal:
    value = row.get(name)
    if value is None or isinstance(value, bool):
        raise TiingoPayloadError(f"Tiingo number is missing: {name}")
    try:
        number = Decimal(str(value))
    except InvalidOperation as error:
        raise TiingoPayloadError(f"Tiingo number is invalid: {name}") from error
    if not number.is_finite():
        raise TiingoPayloadError(f"Tiingo number must be finite: {name}")
    return number

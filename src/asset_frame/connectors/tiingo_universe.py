from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import date, timedelta
from io import BytesIO, TextIOWrapper
from zipfile import BadZipFile, ZipFile

from asset_frame.connectors.tiingo import normalize_ticker
from asset_frame.domain.models import AssetType, FetchRequest

TIINGO_SUPPORTED_TICKERS_URL = "https://apimedia.tiingo.com/docs/tiingo/daily/supported_tickers.zip"
_EXPECTED_COLUMNS = (
    "ticker",
    "exchange",
    "assetType",
    "priceCurrency",
    "startDate",
    "endDate",
)
_US_EXCHANGES = frozenset({"NASDAQ", "NYSE", "NYSE ARCA", "BATS", "AMEX", "NYSE MKT", "NYSE NAT"})
_MAX_UNCOMPRESSED_BYTES = 20 * 1024 * 1024
_EXCHANGE_TEST_TICKER = re.compile(r"^[ACMNPZ]?TEST(?:-[A-Z])?$")


class TiingoUniversePayloadError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TiingoSupportedTicker:
    ticker: str
    exchange: str
    asset_type: AssetType | None
    price_currency: str
    start_date: date | None
    end_date: date | None


def build_supported_tickers_request() -> FetchRequest:
    return FetchRequest(
        url=TIINGO_SUPPORTED_TICKERS_URL,
        headers={"Accept": "application/zip, application/octet-stream"},
        timeout_seconds=60,
    )


def parse_supported_tickers(body: bytes) -> tuple[TiingoSupportedTicker, ...]:
    try:
        with ZipFile(BytesIO(body)) as archive:
            files = [item for item in archive.infolist() if not item.is_dir()]
            if len(files) != 1 or files[0].filename != "supported_tickers.csv":
                raise TiingoUniversePayloadError(
                    "Tiingo supported ticker archive must contain supported_tickers.csv"
                )
            if files[0].file_size > _MAX_UNCOMPRESSED_BYTES:
                raise TiingoUniversePayloadError("Tiingo supported ticker CSV is too large")
            with (
                archive.open(files[0]) as binary_file,
                TextIOWrapper(binary_file, encoding="utf-8-sig", newline="") as text_file,
            ):
                reader = csv.DictReader(text_file)
                if tuple(reader.fieldnames or ()) != _EXPECTED_COLUMNS:
                    raise TiingoUniversePayloadError("Tiingo supported ticker CSV columns changed")
                return tuple(_parse_row(row) for row in reader)
    except BadZipFile as error:
        raise TiingoUniversePayloadError(
            "Tiingo supported ticker payload is not a ZIP archive"
        ) from error


def eligible_us_tickers(
    records: tuple[TiingoSupportedTicker, ...],
    *,
    as_of_date: date,
    end_date_grace_days: int = 7,
) -> tuple[TiingoSupportedTicker, ...]:
    if end_date_grace_days < 0:
        raise ValueError("end_date_grace_days cannot be negative")
    earliest_end_date = as_of_date - timedelta(days=end_date_grace_days)
    eligible = [
        record
        for record in records
        if record.price_currency == "USD"
        and record.exchange in _US_EXCHANGES
        and record.asset_type in {AssetType.EQUITY, AssetType.ETF}
        and record.start_date is not None
        and record.start_date <= as_of_date
        and record.end_date is not None
        and record.end_date >= earliest_end_date
        and _is_collectible_ticker(record.ticker)
    ]
    return tuple(sorted(eligible, key=lambda item: item.ticker))


def _parse_row(row: dict[str, str]) -> TiingoSupportedTicker:
    ticker = _required(row, "ticker").upper()
    if not ticker.isascii():
        raise TiingoUniversePayloadError("Tiingo supported ticker must be ASCII")
    raw_asset_type = _required(row, "assetType")
    asset_type = {
        "Stock": AssetType.EQUITY,
        "ETF": AssetType.ETF,
        "Mutual Fund": None,
    }.get(raw_asset_type)
    return TiingoSupportedTicker(
        ticker=ticker,
        exchange=row.get("exchange", "").strip(),
        asset_type=asset_type,
        price_currency=row.get("priceCurrency", "").strip(),
        start_date=_optional_date(row.get("startDate", ""), "startDate"),
        end_date=_optional_date(row.get("endDate", ""), "endDate"),
    )


def _is_collectible_ticker(ticker: str) -> bool:
    if _EXCHANGE_TEST_TICKER.fullmatch(ticker):
        return False
    try:
        normalize_ticker(ticker)
    except ValueError:
        return False
    return True


def _required(row: dict[str, str], name: str) -> str:
    value = row.get(name, "").strip()
    if not value:
        raise TiingoUniversePayloadError(f"Tiingo supported ticker field is missing: {name}")
    return value


def _optional_date(value: str, name: str) -> date | None:
    if not value.strip():
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise TiingoUniversePayloadError(
            f"Tiingo supported ticker date is invalid: {name}"
        ) from error

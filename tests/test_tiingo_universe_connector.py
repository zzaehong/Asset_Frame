from datetime import date
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from asset_frame.connectors.tiingo_universe import (
    TiingoUniversePayloadError,
    build_supported_tickers_request,
    eligible_us_tickers,
    parse_supported_tickers,
)
from asset_frame.domain.models import AssetType


def _archive(csv_body: str, *, filename: str = "supported_tickers.csv") -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr(filename, csv_body)
    return output.getvalue()


def test_builds_official_supported_ticker_request() -> None:
    request = build_supported_tickers_request()
    assert request.url.startswith("https://apimedia.tiingo.com/")
    assert request.timeout_seconds == 60


def test_parses_and_filters_active_us_stocks_and_etfs() -> None:
    body = _archive(
        "ticker,exchange,assetType,priceCurrency,startDate,endDate\n"
        "AAPL,NASDAQ,Stock,USD,1980-12-12,2026-08-21\n"
        "SPY,NYSE ARCA,ETF,USD,1993-01-29,2026-08-20\n"
        "OLD,NYSE,Stock,USD,2000-01-01,2026-01-01\n"
        "OTC,PINK,Stock,USD,2000-01-01,2026-08-21\n"
        "FUND,NMFQS,Mutual Fund,USD,2000-01-01,2026-08-21\n"
        "CN,SHE,Stock,CNY,2000-01-01,2026-08-21\n"
        "RESERVED,NASDAQ,Stock,USD,,\n"
        "NOEXCHANGE,,Stock,USD,2020-01-01,2026-08-21\n"
        "NEWTYPE,NASDAQ,Index,USD,2020-01-01,2026-08-21\n"
        "ATEST-A,NYSE MKT,Stock,USD,2020-01-01,2026-08-21\n"
    )
    records = parse_supported_tickers(body)
    eligible = eligible_us_tickers(records, as_of_date=date(2026, 8, 21))

    assert [(item.ticker, item.asset_type) for item in eligible] == [
        ("AAPL", AssetType.EQUITY),
        ("SPY", AssetType.ETF),
    ]


def test_rejects_changed_columns_and_invalid_zip() -> None:
    with pytest.raises(TiingoUniversePayloadError, match="columns changed"):
        parse_supported_tickers(_archive("ticker,exchange\nAAPL,NASDAQ\n"))
    with pytest.raises(TiingoUniversePayloadError, match="not a ZIP"):
        parse_supported_tickers(b"not a zip")


def test_ignores_foreign_style_ticker_without_rejecting_archive() -> None:
    body = _archive(
        "ticker,exchange,assetType,priceCurrency,startDate,endDate\n"
        "02Z0:BE,PINK,Stock,USD,2024-03-28,2026-08-21\n"
        "AAPL,NASDAQ,Stock,USD,1980-12-12,2026-08-21\n"
    )

    records = parse_supported_tickers(body)
    eligible = eligible_us_tickers(records, as_of_date=date(2026, 8, 21))

    assert [item.ticker for item in eligible] == ["AAPL"]


def test_rejects_unexpected_archive_member() -> None:
    with pytest.raises(TiingoUniversePayloadError, match="must contain"):
        parse_supported_tickers(_archive("ignored", filename="other.csv"))

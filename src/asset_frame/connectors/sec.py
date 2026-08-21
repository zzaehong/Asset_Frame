from __future__ import annotations

import json
from datetime import date
from typing import Any
from uuid import UUID

from asset_frame.domain.models import (
    FetchRequest,
    FilingDocument,
    IdentifierType,
    RawSnapshot,
    RegulatoryIdentifierRecord,
)

SEC_SOURCE_ID = "sec-edgar-submissions"
SEC_SUBMISSIONS_BASE_URL = "https://data.sec.gov/submissions"
SEC_ARCHIVES_BASE_URL = "https://www.sec.gov/Archives/edgar/data"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"


class SecPayloadError(ValueError):
    pass


def build_submissions_request(cik: str, user_agent: str) -> FetchRequest:
    normalized_cik = normalize_cik(cik)
    if not user_agent.strip():
        raise ValueError("SEC User-Agent is required")
    return FetchRequest(
        url=f"{SEC_SUBMISSIONS_BASE_URL}/CIK{normalized_cik}.json",
        headers={"Accept": "application/json", "User-Agent": user_agent},
    )


def build_ticker_mapping_request(user_agent: str) -> FetchRequest:
    if not user_agent.strip():
        raise ValueError("SEC User-Agent is required")
    return FetchRequest(
        url=SEC_TICKERS_URL,
        headers={"Accept": "application/json", "User-Agent": user_agent},
    )


def parse_ticker_mapping(body: bytes) -> tuple[RegulatoryIdentifierRecord, ...]:
    try:
        payload = json.loads(body)
        fields = payload["fields"]
        rows = payload["data"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise SecPayloadError("invalid SEC ticker mapping payload") from error
    expected_fields = ["cik", "name", "ticker", "exchange"]
    if fields != expected_fields or not isinstance(rows, list):
        raise SecPayloadError("SEC ticker mapping schema is unsupported")

    records = []
    seen: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, list) or len(row) != len(expected_fields):
            raise SecPayloadError("SEC ticker mapping row is invalid")
        cik, name, ticker, exchange = row
        if not isinstance(cik, int) or cik <= 0:
            raise SecPayloadError("SEC ticker mapping CIK is invalid")
        if not all(isinstance(value, str) and value for value in (name, ticker)):
            raise SecPayloadError("SEC ticker mapping required text field is invalid")
        if exchange is not None and not isinstance(exchange, str):
            raise SecPayloadError("SEC ticker mapping exchange field is invalid")
        normalized_ticker = ticker.strip().upper()
        normalized_cik = normalize_cik(str(cik))
        existing = seen.get(normalized_ticker)
        if existing is not None and existing != normalized_cik:
            raise SecPayloadError(f"SEC ticker maps to multiple CIKs: {normalized_ticker}")
        seen[normalized_ticker] = normalized_cik
        records.append(
            RegulatoryIdentifierRecord(
                ticker=normalized_ticker,
                name=name,
                identifier_type=IdentifierType.CIK,
                identifier_value=normalized_cik,
                exchange_code=exchange or None,
            )
        )
    return tuple(records)


def normalize_cik(cik: str) -> str:
    if not cik.isascii() or not cik.isdigit() or len(cik) > 10:
        raise ValueError("CIK must contain at most 10 ASCII digits")
    return cik.zfill(10)


def parse_recent_filings(
    body: bytes,
    *,
    asset_id: UUID,
    snapshot: RawSnapshot,
) -> tuple[FilingDocument, ...]:
    try:
        payload = json.loads(body)
        cik = normalize_cik(str(payload["cik"]))
        recent = payload["filings"]["recent"]
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise SecPayloadError("invalid SEC submissions payload") from error

    required_columns = ("accessionNumber", "filingDate", "form", "primaryDocument")
    if any(not isinstance(recent.get(column), list) for column in required_columns):
        raise SecPayloadError("SEC recent filings columns are missing")
    row_count = len(recent["accessionNumber"])
    if any(len(recent[column]) != row_count for column in required_columns):
        raise SecPayloadError("SEC recent filings columns have different lengths")

    filings = []
    for index in range(row_count):
        accession_number = _required_string(recent, "accessionNumber", index)
        accession_path = accession_number.replace("-", "")
        primary_document = _optional_string(recent, "primaryDocument", index)
        if primary_document is None:
            raise SecPayloadError("SEC primary document is missing")
        filings.append(
            FilingDocument(
                asset_id=asset_id,
                source_id=SEC_SOURCE_ID,
                raw_snapshot_id=snapshot.id,
                accession_number=accession_number,
                form_type=_required_string(recent, "form", index),
                filed_at=_required_date(recent, "filingDate", index),
                published_at=None,
                report_period=_optional_date(recent, "reportDate", index),
                primary_document=primary_document,
                document_url=(
                    f"{SEC_ARCHIVES_BASE_URL}/{int(cik)}/{accession_path}/{primary_document}"
                ),
                metadata={
                    "acceptance_datetime": _optional_string(recent, "acceptanceDateTime", index),
                    "film_number": _optional_string(recent, "filmNumber", index),
                },
            )
        )
    return tuple(filings)


def _value(rows: dict[str, Any], name: str, index: int) -> object | None:
    column = rows.get(name)
    if not isinstance(column, list) or index >= len(column):
        return None
    return column[index]


def _required_string(rows: dict[str, Any], name: str, index: int) -> str:
    value = _optional_string(rows, name, index)
    if value is None:
        raise SecPayloadError(f"SEC {name} is missing")
    return value


def _optional_string(rows: dict[str, Any], name: str, index: int) -> str | None:
    value = _value(rows, name, index)
    return value if isinstance(value, str) and value else None


def _required_date(rows: dict[str, Any], name: str, index: int) -> date:
    value = _optional_date(rows, name, index)
    if value is None:
        raise SecPayloadError(f"SEC {name} is missing or invalid")
    return value


def _optional_date(rows: dict[str, Any], name: str, index: int) -> date | None:
    value = _optional_string(rows, name, index)
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise SecPayloadError(f"SEC {name} is invalid") from error

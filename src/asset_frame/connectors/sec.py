from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from asset_frame.domain.models import (
    FetchRequest,
    FilingDocument,
    FinancialFact,
    IdentifierType,
    RawSnapshot,
    RegulatoryIdentifierRecord,
)

SEC_SOURCE_ID = "sec-edgar-submissions"
SEC_SUBMISSIONS_BASE_URL = "https://data.sec.gov/submissions"
SEC_ARCHIVES_BASE_URL = "https://www.sec.gov/Archives/edgar/data"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_MUTUAL_FUND_TICKERS_URL = "https://www.sec.gov/files/company_tickers_mf.json"
SEC_COMPANY_FACTS_BASE_URL = "https://data.sec.gov/api/xbrl/companyfacts"


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


def build_mutual_fund_ticker_mapping_request(user_agent: str) -> FetchRequest:
    if not user_agent.strip():
        raise ValueError("SEC User-Agent is required")
    return FetchRequest(
        url=SEC_MUTUAL_FUND_TICKERS_URL,
        headers={"Accept": "application/json", "User-Agent": user_agent},
    )


def build_company_facts_request(cik: str, user_agent: str) -> FetchRequest:
    if not user_agent.strip():
        raise ValueError("SEC User-Agent is required")
    return FetchRequest(
        url=f"{SEC_COMPANY_FACTS_BASE_URL}/CIK{normalize_cik(cik)}.json",
        headers={"Accept": "application/json", "User-Agent": user_agent},
    )


def parse_company_facts(
    body: bytes,
    *,
    asset_id: UUID,
    snapshot: RawSnapshot,
    expected_cik: str,
    allowed_concepts: frozenset[str],
) -> tuple[FinancialFact, ...]:
    try:
        payload = json.loads(body)
        cik = normalize_cik(str(payload["cik"]))
        taxonomies = payload["facts"]
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise SecPayloadError("invalid SEC company facts payload") from error
    if cik != normalize_cik(expected_cik) or not isinstance(taxonomies, dict):
        raise SecPayloadError("SEC company facts CIK or facts do not match request")
    facts = []
    for taxonomy, concepts in taxonomies.items():
        if not isinstance(taxonomy, str) or not isinstance(concepts, dict):
            raise SecPayloadError("SEC company facts taxonomy is invalid")
        for concept, definition in concepts.items():
            if concept not in allowed_concepts:
                continue
            if not isinstance(definition, dict) or not isinstance(definition.get("units"), dict):
                raise SecPayloadError("SEC company fact definition is invalid")
            for unit, observations in definition["units"].items():
                if not isinstance(unit, str) or not isinstance(observations, list):
                    raise SecPayloadError("SEC company fact units are invalid")
                for row in observations:
                    fact = _sec_fact(row, asset_id, snapshot, taxonomy, concept, unit)
                    if fact is not None:
                        facts.append(fact)
    return tuple(facts)


def _sec_fact(
    row: object,
    asset_id: UUID,
    snapshot: RawSnapshot,
    taxonomy: str,
    concept: str,
    unit: str,
) -> FinancialFact | None:
    if not isinstance(row, dict):
        raise SecPayloadError("SEC company fact observation is invalid")
    form = row.get("form")
    if not isinstance(form, str) or form.upper().removesuffix("/A") not in {
        "10-K",
        "10-Q",
        "20-F",
        "40-F",
        "8-K",
        "6-K",
    }:
        return None
    try:
        value = Decimal(str(row["val"]))
        period_end = date.fromisoformat(row["end"])
        period_start = date.fromisoformat(row["start"]) if row.get("start") else None
        filed_at = datetime.combine(date.fromisoformat(row["filed"]), datetime.min.time(), UTC)
    except (KeyError, TypeError, ValueError, InvalidOperation) as error:
        raise SecPayloadError("SEC company fact observation fields are invalid") from error
    dimensions = {
        name: str(row[name]) for name in ("fy", "fp", "form", "frame") if row.get(name) is not None
    }
    return FinancialFact(
        asset_id=asset_id,
        source_id=SEC_SOURCE_ID,
        raw_snapshot_id=snapshot.id,
        taxonomy=taxonomy,
        concept=concept,
        unit=unit,
        value=value,
        period_start=period_start,
        period_end=period_end,
        filed_at=filed_at,
        published_at=None,
        revised_at=None,
        accession_number=str(row["accn"]) if row.get("accn") else None,
        dimensions=dimensions,
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


def parse_mutual_fund_ticker_mapping(body: bytes) -> tuple[RegulatoryIdentifierRecord, ...]:
    try:
        payload = json.loads(body)
        fields = payload["fields"]
        rows = payload["data"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise SecPayloadError("invalid SEC mutual fund ticker mapping payload") from error
    expected_fields = ["cik", "seriesId", "classId", "symbol"]
    if fields != expected_fields or not isinstance(rows, list):
        raise SecPayloadError("SEC mutual fund ticker mapping schema is unsupported")

    records = []
    seen: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, list) or len(row) != len(expected_fields):
            raise SecPayloadError("SEC mutual fund ticker mapping row is invalid")
        cik, series_id, class_id, symbol = row
        if not isinstance(cik, int) or cik <= 0:
            raise SecPayloadError("SEC mutual fund ticker mapping CIK is invalid")
        if not all(
            isinstance(value, str) and value for value in (series_id, class_id)
        ) or not isinstance(symbol, str):
            raise SecPayloadError("SEC mutual fund ticker mapping text field is invalid")
        if not symbol.strip():
            continue
        normalized_ticker = symbol.strip().upper()
        normalized_cik = normalize_cik(str(cik))
        existing = seen.get(normalized_ticker)
        if existing is not None and existing != normalized_cik:
            raise SecPayloadError(
                f"SEC mutual fund ticker maps to multiple CIKs: {normalized_ticker}"
            )
        seen[normalized_ticker] = normalized_cik
        records.append(
            RegulatoryIdentifierRecord(
                ticker=normalized_ticker,
                name=None,
                identifier_type=IdentifierType.CIK,
                identifier_value=normalized_cik,
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
        document_url = f"{SEC_ARCHIVES_BASE_URL}/{int(cik)}/{accession_path}/"
        if primary_document is not None:
            document_url += primary_document
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
                document_url=document_url,
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

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlencode
from uuid import UUID
from xml.etree import ElementTree

from asset_frame.domain.models import (
    FetchRequest,
    FilingDocument,
    FinancialFact,
    IdentifierType,
    RawSnapshot,
    RegulatoryIdentifierRecord,
)

OPENDART_SOURCE_ID = "opendart"
OPENDART_LIST_URL = "https://opendart.fss.or.kr/api/list.json"
OPENDART_VIEWER_URL = "https://dart.fss.or.kr/dsaf001/main.do"
OPENDART_CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
OPENDART_FINANCIALS_URL = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
_REPORT_PERIOD_END = {
    "11013": (3, 31),
    "11012": (6, 30),
    "11014": (9, 30),
    "11011": (12, 31),
}


class OpenDartPayloadError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ParsedDisclosurePage:
    filings: tuple[FilingDocument, ...]
    page_no: int
    total_pages: int


def build_disclosure_request(
    *,
    api_key: str,
    corp_code: str,
    start_date: date,
    end_date: date,
    page_no: int,
    page_count: int = 100,
) -> FetchRequest:
    if not api_key.strip():
        raise ValueError("OpenDART API key is required")
    if not corp_code.isascii() or not corp_code.isdigit() or len(corp_code) != 8:
        raise ValueError("OpenDART corp_code must contain exactly 8 ASCII digits")
    if start_date > end_date:
        raise ValueError("OpenDART start date must not be after end date")
    if page_no < 1:
        raise ValueError("OpenDART page number must be positive")
    if not 1 <= page_count <= 100:
        raise ValueError("OpenDART page count must be between 1 and 100")
    query = urlencode(
        {
            "crtfc_key": api_key,
            "corp_code": corp_code,
            "bgn_de": start_date.strftime("%Y%m%d"),
            "end_de": end_date.strftime("%Y%m%d"),
            "page_no": page_no,
            "page_count": page_count,
        }
    )
    return FetchRequest(url=f"{OPENDART_LIST_URL}?{query}", headers={"Accept": "application/json"})


def build_corp_code_request(api_key: str) -> FetchRequest:
    if not api_key.strip():
        raise ValueError("OpenDART API key is required")
    return FetchRequest(
        url=f"{OPENDART_CORP_CODE_URL}?{urlencode({'crtfc_key': api_key})}",
        headers={"Accept": "application/zip"},
    )


def build_financial_facts_request(
    *, api_key: str, corp_code: str, business_year: int, report_code: str, fs_div: str
) -> FetchRequest:
    if not api_key.strip():
        raise ValueError("OpenDART API key is required")
    if not corp_code.isascii() or not corp_code.isdigit() or len(corp_code) != 8:
        raise ValueError("OpenDART corp_code must contain exactly 8 ASCII digits")
    if business_year < 2015 or business_year > date.today().year:
        raise ValueError("OpenDART business year is outside the supported range")
    if report_code not in _REPORT_PERIOD_END:
        raise ValueError("OpenDART report code is unsupported")
    if fs_div not in {"CFS", "OFS"}:
        raise ValueError("OpenDART fs_div must be CFS or OFS")
    query = urlencode(
        {
            "crtfc_key": api_key,
            "corp_code": corp_code,
            "bsns_year": business_year,
            "reprt_code": report_code,
            "fs_div": fs_div,
        }
    )
    return FetchRequest(
        url=f"{OPENDART_FINANCIALS_URL}?{query}",
        headers={"Accept": "application/json"},
    )


def parse_financial_facts(
    body: bytes,
    *,
    asset_id: UUID,
    snapshot: RawSnapshot,
    expected_corp_code: str,
    business_year: int,
    report_code: str,
    fs_div: str,
    allowed_concepts: frozenset[str],
) -> tuple[FinancialFact, ...]:
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise OpenDartPayloadError("invalid OpenDART financial facts payload") from error
    if payload.get("status") == "013":
        return ()
    if payload.get("status") != "000" or not isinstance(payload.get("list"), list):
        raise OpenDartPayloadError(
            f"OpenDART financial facts API error {payload.get('status')}: {payload.get('message')}"
        )
    month, day = _REPORT_PERIOD_END[report_code]
    period_end = date(business_year, month, day)
    facts = []
    for row in payload["list"]:
        if not isinstance(row, dict) or row.get("corp_code") != expected_corp_code:
            raise OpenDartPayloadError("OpenDART financial fact corp_code does not match request")
        concept = _required_string(row, "account_id")
        if concept not in allowed_concepts:
            continue
        amount = _dart_amount(row.get("thstrm_amount"))
        if amount is None:
            continue
        receipt_number = _required_string(row, "rcept_no")
        try:
            filed_date = date(
                int(receipt_number[:4]), int(receipt_number[4:6]), int(receipt_number[6:8])
            )
        except (ValueError, IndexError) as error:
            raise OpenDartPayloadError(
                "OpenDART financial fact receipt number is invalid"
            ) from error
        facts.append(
            FinancialFact(
                asset_id=asset_id,
                source_id=OPENDART_SOURCE_ID,
                raw_snapshot_id=snapshot.id,
                taxonomy="dart-ifrs",
                concept=concept,
                unit=_optional_string(row, "currency") or "KRW",
                value=amount,
                period_start=None if row.get("sj_div") == "BS" else date(business_year, 1, 1),
                period_end=period_end,
                filed_at=datetime.combine(filed_date, datetime.min.time(), UTC),
                published_at=None,
                revised_at=None,
                accession_number=receipt_number,
                dimensions={
                    "fs_div": fs_div,
                    "statement": str(row.get("sj_div", "")),
                    "report_code": report_code,
                    "business_year": str(business_year),
                    "account_name": str(row.get("account_nm", "")),
                },
            )
        )
    return tuple(facts)


def _dart_amount(value: object) -> Decimal | None:
    if value in (None, "", "-"):
        return None
    try:
        normalized = str(value).replace(",", "").strip()
        if normalized.startswith("(") and normalized.endswith(")"):
            normalized = f"-{normalized[1:-1]}"
        return Decimal(normalized)
    except InvalidOperation as error:
        raise OpenDartPayloadError("OpenDART financial fact amount is invalid") from error


def parse_corp_code_archive(body: bytes) -> tuple[RegulatoryIdentifierRecord, ...]:
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            names = archive.namelist()
            if len(names) != 1 or names[0].rsplit("/", 1)[-1].upper() != "CORPCODE.XML":
                raise OpenDartPayloadError("OpenDART corp code archive layout is unsupported")
            xml_body = archive.read(names[0])
        root = ElementTree.fromstring(xml_body)
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as error:
        raise OpenDartPayloadError("invalid OpenDART corp code archive") from error

    records = []
    seen: dict[str, str] = {}
    for item in root.findall("list"):
        stock_code = _xml_text(item, "stock_code", required=False)
        if not stock_code:
            continue
        if not stock_code.isascii() or not stock_code.isalnum() or len(stock_code) != 6:
            raise OpenDartPayloadError("OpenDART stock code is invalid")
        corp_code = _xml_text(item, "corp_code")
        if not corp_code.isascii() or not corp_code.isdigit() or len(corp_code) != 8:
            raise OpenDartPayloadError("OpenDART corp code is invalid")
        existing = seen.get(stock_code)
        if existing is not None and existing != corp_code:
            raise OpenDartPayloadError(f"OpenDART ticker maps to multiple corp codes: {stock_code}")
        seen[stock_code] = corp_code
        records.append(
            RegulatoryIdentifierRecord(
                ticker=stock_code,
                name=_xml_text(item, "corp_name"),
                identifier_type=IdentifierType.DART_CORP_CODE,
                identifier_value=corp_code,
                modified_at=_compact_date(_xml_text(item, "modify_date")),
            )
        )
    return tuple(records)


def parse_disclosure_page(
    body: bytes,
    *,
    asset_id: UUID,
    snapshot: RawSnapshot,
    expected_corp_code: str,
) -> ParsedDisclosurePage:
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise OpenDartPayloadError("invalid OpenDART JSON payload") from error
    if not isinstance(payload, dict):
        raise OpenDartPayloadError("OpenDART payload must be an object")

    status = payload.get("status")
    if status == "013":
        return ParsedDisclosurePage((), 1, 0)
    if status != "000":
        message = payload.get("message")
        raise OpenDartPayloadError(f"OpenDART API error {status}: {message}")

    page_no = _positive_int(payload, "page_no")
    total_pages = _non_negative_int(payload, "total_page")
    rows = payload.get("list")
    if not isinstance(rows, list):
        raise OpenDartPayloadError("OpenDART disclosure list is missing")

    filings = []
    for row in rows:
        if not isinstance(row, dict):
            raise OpenDartPayloadError("OpenDART disclosure row must be an object")
        corp_code = _required_string(row, "corp_code")
        if corp_code != expected_corp_code:
            raise OpenDartPayloadError("OpenDART response corp_code does not match request")
        receipt_number = _required_string(row, "rcept_no")
        filings.append(
            FilingDocument(
                asset_id=asset_id,
                source_id=OPENDART_SOURCE_ID,
                raw_snapshot_id=snapshot.id,
                accession_number=receipt_number,
                form_type=_required_string(row, "report_nm"),
                filed_at=_required_date(row, "rcept_dt"),
                published_at=None,
                report_period=None,
                primary_document=None,
                document_url=f"{OPENDART_VIEWER_URL}?rcpNo={receipt_number}",
                metadata={
                    "corp_code": corp_code,
                    "corp_name": _optional_string(row, "corp_name"),
                    "corp_cls": _optional_string(row, "corp_cls"),
                    "stock_code": _optional_string(row, "stock_code"),
                    "filer_name": _optional_string(row, "flr_nm"),
                    "remark": _optional_string(row, "rm"),
                },
            )
        )
    return ParsedDisclosurePage(tuple(filings), page_no, total_pages)


def _required_string(row: dict[str, Any], name: str) -> str:
    value = _optional_string(row, name)
    if value is None:
        raise OpenDartPayloadError(f"OpenDART field is missing: {name}")
    return value


def _optional_string(row: dict[str, Any], name: str) -> str | None:
    value = row.get(name)
    return value if isinstance(value, str) and value else None


def _required_date(row: dict[str, Any], name: str) -> date:
    value = _required_string(row, name)
    if len(value) != 8 or not value.isascii() or not value.isdigit():
        raise OpenDartPayloadError(f"OpenDART date is invalid: {name}")
    try:
        return date(int(value[0:4]), int(value[4:6]), int(value[6:8]))
    except ValueError as error:
        raise OpenDartPayloadError(f"OpenDART date is invalid: {name}") from error


def _positive_int(payload: dict[str, Any], name: str) -> int:
    value = _non_negative_int(payload, name)
    if value < 1:
        raise OpenDartPayloadError(f"OpenDART field must be positive: {name}")
    return value


def _non_negative_int(payload: dict[str, Any], name: str) -> int:
    try:
        value = int(payload[name])
    except (KeyError, TypeError, ValueError) as error:
        raise OpenDartPayloadError(f"OpenDART integer field is invalid: {name}") from error
    if value < 0:
        raise OpenDartPayloadError(f"OpenDART field must not be negative: {name}")
    return value


def _xml_text(item: ElementTree.Element, name: str, *, required: bool = True) -> str:
    child = item.find(name)
    value = child.text.strip() if child is not None and child.text else ""
    if required and not value:
        raise OpenDartPayloadError(f"OpenDART corp code field is missing: {name}")
    return value


def _compact_date(value: str) -> date:
    if len(value) != 8 or not value.isascii() or not value.isdigit():
        raise OpenDartPayloadError("OpenDART modify date is invalid")
    try:
        return date(int(value[0:4]), int(value[4:6]), int(value[6:8]))
    except ValueError as error:
        raise OpenDartPayloadError("OpenDART modify date is invalid") from error

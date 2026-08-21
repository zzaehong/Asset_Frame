from __future__ import annotations

import json
from datetime import date
from typing import Any
from uuid import UUID

from asset_frame.domain.models import FetchRequest, FilingDocument, RawSnapshot

SEC_SOURCE_ID = "sec-edgar-submissions"
SEC_SUBMISSIONS_BASE_URL = "https://data.sec.gov/submissions"
SEC_ARCHIVES_BASE_URL = "https://www.sec.gov/Archives/edgar/data"


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

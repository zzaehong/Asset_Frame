from datetime import date
from pathlib import Path
from uuid import UUID

import pytest

from asset_frame.domain.models import FilingDocument
from asset_frame.ingestion.filing_policy import load_filing_policy, select_major_filings


def _filing(source_id: str, form_type: str) -> FilingDocument:
    return FilingDocument(
        asset_id=UUID(int=1),
        source_id=source_id,
        raw_snapshot_id=UUID(int=2),
        accession_number=f"accession-{form_type}",
        form_type=form_type,
        filed_at=date(2026, 8, 21),
        published_at=None,
        report_period=None,
        primary_document=None,
        document_url="https://example.test/filing",
    )


def test_selects_major_sec_forms_and_fund_reports() -> None:
    policy = load_filing_policy(Path("config/filing-policy.toml"))
    selected = select_major_filings(
        (
            _filing("sec-edgar-submissions", "10-K"),
            _filing("sec-edgar-submissions", "8-K/A"),
            _filing("sec-edgar-submissions", "NPORT-P"),
            _filing("sec-edgar-submissions", "4"),
        ),
        policy,
    )

    assert [item.form_type for item in selected] == ["10-K", "8-K/A", "NPORT-P"]
    assert [item.metadata["selection_category"] for item in selected] == [
        "periodic",
        "event",
        "fund",
    ]


def test_selects_corrected_opendart_major_reports() -> None:
    policy = load_filing_policy(Path("config/filing-policy.toml"))
    selected = select_major_filings(
        (
            _filing("opendart", "[기재정정]사업보고서 (2025.12)"),
            _filing("opendart", "주요사항보고서(유상증자결정)"),
            _filing("opendart", "임원ㆍ주요주주특정증권등소유상황보고서"),
        ),
        policy,
    )

    assert [item.metadata["selection_category"] for item in selected] == [
        "periodic",
        "event",
    ]
    assert all(item.metadata["selection_policy"] == "major-filings-v1" for item in selected)


def test_rejects_unknown_source() -> None:
    policy = load_filing_policy(Path("config/filing-policy.toml"))
    with pytest.raises(ValueError, match="does not support"):
        select_major_filings((_filing("unknown", "10-K"),), policy)

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from asset_frame.connectors.gdelt import build_news_request, parse_news
from asset_frame.connectors.opendart import (
    build_financial_facts_request,
    parse_financial_facts,
)
from asset_frame.connectors.sec import build_company_facts_request, parse_company_facts
from asset_frame.domain.models import RawSnapshot
from asset_frame.ingestion.financial_policy import load_financial_fact_policy


def _snapshot(source_id: str) -> RawSnapshot:
    return RawSnapshot(
        id=UUID(int=10),
        source_id=source_id,
        request_url="https://example.test",
        fetched_at=datetime(2026, 8, 21, 12, tzinfo=UTC),
        http_status=200,
        content_type="application/json",
        content_length=1,
        sha256="0" * 64,
        storage_path="raw.bin",
    )


def test_sec_company_facts_selects_policy_concepts_and_major_forms() -> None:
    policy = load_financial_fact_policy(Path("config/financial-facts.toml"))
    body = json.dumps(
        {
            "cik": 320193,
            "facts": {
                "us-gaap": {
                    "Assets": {
                        "units": {
                            "USD": [
                                {
                                    "end": "2026-06-30",
                                    "val": 100,
                                    "accn": "0000320193-26-000001",
                                    "fy": 2026,
                                    "fp": "Q2",
                                    "form": "10-Q",
                                    "filed": "2026-08-01",
                                },
                                {
                                    "end": "2026-07-01",
                                    "val": 101,
                                    "form": "4",
                                    "filed": "2026-08-02",
                                },
                            ]
                        }
                    },
                    "UnselectedConcept": {"units": {"USD": []}},
                }
            },
        }
    ).encode()

    request = build_company_facts_request("320193", "Asset Frame admin@example.com")
    facts = parse_company_facts(
        body,
        asset_id=UUID(int=1),
        snapshot=_snapshot("sec-edgar-submissions"),
        expected_cik="320193",
        allowed_concepts=policy.sec_concepts,
    )

    assert request.url.endswith("CIK0000320193.json")
    assert len(facts) == 1
    assert facts[0].concept == "Assets"
    assert facts[0].value == Decimal("100")
    assert facts[0].dimensions["form"] == "10-Q"


def test_opendart_financial_facts_selects_current_amount() -> None:
    policy = load_financial_fact_policy(Path("config/financial-facts.toml"))
    body = json.dumps(
        {
            "status": "000",
            "message": "정상",
            "list": [
                {
                    "rcept_no": "20260318000001",
                    "corp_code": "00126380",
                    "fs_div": "CFS",
                    "sj_div": "BS",
                    "account_id": "ifrs-full_Assets",
                    "account_nm": "자산총계",
                    "thstrm_amount": "1,234",
                    "currency": "KRW",
                },
                {
                    "rcept_no": "20260318000001",
                    "corp_code": "00126380",
                    "fs_div": "CFS",
                    "sj_div": "BS",
                    "account_id": "dart_Unselected",
                    "thstrm_amount": "999",
                },
            ],
        },
        ensure_ascii=False,
    ).encode()

    request = build_financial_facts_request(
        api_key="secret",
        corp_code="00126380",
        business_year=2025,
        report_code="11011",
        fs_div="CFS",
    )
    facts = parse_financial_facts(
        body,
        asset_id=UUID(int=2),
        snapshot=_snapshot("opendart"),
        expected_corp_code="00126380",
        business_year=2025,
        report_code="11011",
        fs_div="CFS",
        allowed_concepts=policy.opendart_concepts,
    )

    assert "fnlttSinglAcntAll.json" in request.url
    assert len(facts) == 1
    assert facts[0].value == Decimal("1234")
    assert facts[0].period_end == date(2025, 12, 31)


def test_gdelt_recent_news_contract_and_deduplication() -> None:
    start = datetime(2026, 8, 20, tzinfo=UTC)
    end = start + timedelta(days=1)
    request = build_news_request(query='"Apple Inc"', start_at=start, end_at=end, max_records=25)
    article = {
        "url": "https://news.example/apple",
        "title": "Apple update",
        "seendate": "20260821T010203Z",
        "domain": "news.example",
        "language": "English",
        "sourcecountry": "United States",
    }
    mentions = parse_news(
        json.dumps({"articles": [article, article]}).encode(),
        asset_id=UUID(int=3),
        snapshot=_snapshot("gdelt-doc"),
        matched_query='"Apple Inc"',
    )

    assert request.url.startswith("https://api.gdeltproject.org/api/v2/doc/doc?")
    assert len(mentions) == 1
    assert mentions[0].published_at == datetime(2026, 8, 21, 1, 2, 3, tzinfo=UTC)
    with pytest.raises(ValueError, match="7 days"):
        build_news_request(
            query="Apple", start_at=start, end_at=start + timedelta(days=8), max_records=25
        )
    with pytest.raises(ValueError, match="between 1 and 50"):
        build_news_request(query="Apple", start_at=start, end_at=end, max_records=51)

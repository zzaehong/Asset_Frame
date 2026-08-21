import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from asset_frame.dashboard.repository import PostgresDashboardRepository
from asset_frame.web.app import create_app

ASSET_ID = UUID("0333a134-7e87-52ed-991f-1e3d9742509e")


class FakeDashboardRepository:
    def health(self) -> dict[str, object]:
        return {"status": "ok", "database": "asset_frame", "user": "reader"}

    def overview(self) -> dict[str, object]:
        return {
            "generated_at": datetime(2026, 8, 22, tzinfo=UTC),
            "totals": {"assets": 2},
            "sources": [{"source_id": "official-source"}],
        }

    def recent_runs(self, *, limit: int) -> list[dict[str, object]]:
        return [{"source_id": "official-source", "limit": limit}]

    def recent_snapshots(self, *, limit: int) -> list[dict[str, object]]:
        return [{"source_id": "official-source", "limit": limit}]

    def assets(
        self,
        *,
        query: str | None,
        country_code: str | None,
        asset_type: str | None,
        limit: int,
        offset: int,
    ) -> dict[str, object]:
        return {
            "total": 1,
            "limit": limit,
            "offset": offset,
            "items": [
                {
                    "ticker": query,
                    "country_code": country_code,
                    "asset_type": asset_type,
                }
            ],
        }

    def asset_detail(self, *, asset_id: UUID) -> dict[str, object] | None:
        if asset_id != ASSET_ID:
            return None
        return {
            "asset_id": asset_id,
            "ticker": "AAPL",
            "price_records": 1254,
            "earliest_price_date": "2021-08-23",
            "latest_price_date": "2026-08-20",
            "filing_records": 1001,
        }

    def asset_prices(self, *, asset_id: UUID, limit: int, offset: int) -> dict[str, object]:
        return {
            "total": 1254,
            "limit": limit,
            "offset": offset,
            "items": [{"asset_id": asset_id, "trading_date": "2026-08-20"}],
        }

    def asset_filings(self, *, asset_id: UUID, limit: int, offset: int) -> dict[str, object]:
        return {
            "total": 1001,
            "limit": limit,
            "offset": offset,
            "items": [{"asset_id": asset_id, "form_type": "10-K"}],
        }


def endpoint(app, path: str):  # type: ignore[no-untyped-def]
    return next(route.endpoint for route in app.routes if route.path == path)


def test_dashboard_app_exposes_html_and_read_only_api_routes() -> None:
    app = create_app(repository=FakeDashboardRepository())

    html = endpoint(app, "/")()
    health = endpoint(app, "/api/health")()
    assets = endpoint(app, "/api/assets")(
        q="AAPL", country_code="US", asset_type="equity", limit=20, offset=0
    )
    detail = endpoint(app, "/api/assets/{asset_id}")(asset_id=ASSET_ID)
    prices = endpoint(app, "/api/assets/{asset_id}/prices")(asset_id=ASSET_ID, limit=50, offset=100)
    filings = endpoint(app, "/api/assets/{asset_id}/filings")(asset_id=ASSET_ID, limit=25, offset=0)

    assert "Asset Frame · Data Console" in html
    assert "투자 추천이나 매매 판단을 제공하지 않습니다" in html
    assert 'data-asset-type="equity"' in html
    assert "가격 기간" in html
    assert "수집된 공시 없음" in html
    assert 'id="asset-detail"' in html
    assert health == {"status": "ok", "database": "asset_frame", "user": "reader"}
    assert assets["items"][0] == {
        "ticker": "AAPL",
        "country_code": "US",
        "asset_type": "equity",
    }
    assert detail["earliest_price_date"] == "2021-08-23"
    assert prices["offset"] == 100
    assert filings["items"][0]["form_type"] == "10-K"
    assert {
        "/",
        "/api/overview",
        "/api/runs",
        "/api/snapshots",
        "/api/assets",
        "/api/assets/{asset_id}",
        "/api/assets/{asset_id}/prices",
        "/api/assets/{asset_id}/filings",
    } <= {route.path for route in app.routes}


def test_dashboard_reports_unknown_asset() -> None:
    app = create_app(repository=FakeDashboardRepository())

    with pytest.raises(HTTPException) as captured:
        endpoint(app, "/api/assets/{asset_id}")(asset_id=uuid4())

    assert captured.value.status_code == 404


def test_dashboard_reports_missing_database_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app()

    with pytest.raises(HTTPException) as captured:
        endpoint(app, "/api/health")()

    assert captured.value.status_code == 503
    assert captured.value.detail == "DATABASE_URL is not configured"


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL is not configured")
def test_postgres_dashboard_queries_current_data_without_writes() -> None:
    repository = PostgresDashboardRepository(os.environ["DATABASE_URL"])

    health = repository.health()
    overview = repository.overview()
    assets = repository.assets(
        query="AAPL",
        country_code="US",
        asset_type="equity",
        limit=10,
        offset=0,
    )

    assert health["status"] == "ok"
    assert overview["totals"]["enabled_sources"] >= 4
    assert overview["totals"]["assets"] >= 1
    assert assets["total"] >= 1
    assert assets["items"][0]["ticker"] == "AAPL"
    assert assets["items"][0]["price_records"] >= 1
    assert assets["items"][0]["earliest_price_date"] <= assets["items"][0]["latest_price_date"]

    asset_id = assets["items"][0]["asset_id"]
    detail = repository.asset_detail(asset_id=asset_id)
    prices = repository.asset_prices(asset_id=asset_id, limit=5, offset=0)
    filings = repository.asset_filings(asset_id=asset_id, limit=5, offset=0)

    assert detail is not None
    assert detail["ticker"] == "AAPL"
    assert prices["total"] >= len(prices["items"]) >= 1
    assert prices["items"][0]["trading_date"] <= detail["latest_price_date"]
    assert filings["total"] >= len(filings["items"]) >= 1

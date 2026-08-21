import os
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from asset_frame.dashboard.repository import PostgresDashboardRepository
from asset_frame.web.app import create_app


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


def endpoint(app, path: str):  # type: ignore[no-untyped-def]
    return next(route.endpoint for route in app.routes if route.path == path)


def test_dashboard_app_exposes_html_and_read_only_api_routes() -> None:
    app = create_app(repository=FakeDashboardRepository())

    html = endpoint(app, "/")()
    health = endpoint(app, "/api/health")()
    assets = endpoint(app, "/api/assets")(
        q="AAPL", country_code="US", asset_type="equity", limit=20, offset=0
    )

    assert "Asset Frame · Data Console" in html
    assert "투자 추천이나 매매 판단을 제공하지 않습니다" in html
    assert health == {"status": "ok", "database": "asset_frame", "user": "reader"}
    assert assets["items"][0] == {
        "ticker": "AAPL",
        "country_code": "US",
        "asset_type": "equity",
    }
    assert {"/", "/api/overview", "/api/runs", "/api/snapshots", "/api/assets"} <= {
        route.path for route in app.routes
    }


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

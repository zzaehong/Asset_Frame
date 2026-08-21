from __future__ import annotations

import os
from importlib.resources import files
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from asset_frame.dashboard.repository import (
    DashboardRepository,
    DashboardUnavailable,
    PostgresDashboardRepository,
)


def create_app(
    *,
    repository: DashboardRepository | None = None,
    database_url: str | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Asset Frame Data Console",
        version="0.1.0",
        description="Read-only data lineage and ingestion dashboard",
    )
    configured_url = database_url or os.getenv("DATABASE_URL")

    def dashboard_repository() -> DashboardRepository:
        if repository is not None:
            return repository
        if not configured_url:
            raise HTTPException(status_code=503, detail="DATABASE_URL is not configured")
        return PostgresDashboardRepository(configured_url)

    def safely(call):  # type: ignore[no-untyped-def]
        try:
            return call()
        except DashboardUnavailable:
            raise HTTPException(
                status_code=503, detail="dashboard database is unavailable"
            ) from None

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def dashboard() -> str:
        return files("asset_frame.web").joinpath("dashboard.html").read_text(encoding="utf-8")

    @app.get("/api/health")
    def health() -> dict[str, object]:
        return safely(lambda: dashboard_repository().health())

    @app.get("/api/overview")
    def overview() -> dict[str, object]:
        return safely(lambda: dashboard_repository().overview())

    @app.get("/api/runs")
    def runs(limit: int = Query(default=30, ge=1, le=200)) -> dict[str, object]:
        items = safely(lambda: dashboard_repository().recent_runs(limit=limit))
        return {"items": items, "limit": limit}

    @app.get("/api/snapshots")
    def snapshots(limit: int = Query(default=30, ge=1, le=200)) -> dict[str, object]:
        items = safely(lambda: dashboard_repository().recent_snapshots(limit=limit))
        return {"items": items, "limit": limit}

    @app.get("/api/assets")
    def assets(
        q: str | None = Query(default=None, max_length=100),
        country_code: str | None = Query(default=None, pattern="^(KR|US)$"),
        asset_type: str | None = Query(default=None, pattern="^(equity|etf)$"),
        limit: int = Query(default=100, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, object]:
        return safely(
            lambda: dashboard_repository().assets(
                query=q,
                country_code=country_code,
                asset_type=asset_type,
                limit=limit,
                offset=offset,
            )
        )

    def require_asset(asset_id: UUID) -> dict[str, object]:
        item = safely(lambda: dashboard_repository().asset_detail(asset_id=asset_id))
        if item is None:
            raise HTTPException(status_code=404, detail="asset was not found")
        return item

    @app.get("/api/assets/{asset_id}")
    def asset_detail(asset_id: UUID) -> dict[str, object]:
        return require_asset(asset_id)

    @app.get("/api/assets/{asset_id}/prices")
    def asset_prices(
        asset_id: UUID,
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, object]:
        require_asset(asset_id)
        return safely(
            lambda: dashboard_repository().asset_prices(
                asset_id=asset_id, limit=limit, offset=offset
            )
        )

    @app.get("/api/assets/{asset_id}/filings")
    def asset_filings(
        asset_id: UUID,
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, object]:
        require_asset(asset_id)
        return safely(
            lambda: dashboard_repository().asset_filings(
                asset_id=asset_id, limit=limit, offset=offset
            )
        )

    return app


app = create_app()

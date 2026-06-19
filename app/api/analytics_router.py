"""Read-only analytics routes for DF Local Foundation."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request

from app.analytics_models import model_to_dict
from app.analytics_services import (
    AnalyticsReadError,
    build_freshness_response,
    build_overview_response,
    build_queue_response,
    build_systems_response,
)

router = APIRouter()


async def get_analytics_reader(request: Request) -> Any:
    """Resolve the request-scoped analytics reader. Overridable in tests."""
    return request.app.state.analytics_reader


def _analytics_unavailable(exc: AnalyticsReadError) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "status": "unavailable",
            "error_class": "analytics_read_failure",
            "schema_version": "v1",
        },
    )


@router.get("/api/v1/analytics/overview")
async def get_overview(reader: Annotated[Any, Depends(get_analytics_reader)]) -> dict[str, Any]:
    try:
        return model_to_dict(await build_overview_response(reader))
    except AnalyticsReadError as exc:
        raise _analytics_unavailable(exc) from exc


@router.get("/api/v1/analytics/systems")
async def get_systems(reader: Annotated[Any, Depends(get_analytics_reader)]) -> dict[str, Any]:
    try:
        return model_to_dict(await build_systems_response(reader))
    except AnalyticsReadError as exc:
        raise _analytics_unavailable(exc) from exc


@router.get("/api/v1/analytics/queue")
async def get_queue(reader: Annotated[Any, Depends(get_analytics_reader)]) -> dict[str, Any]:
    try:
        return model_to_dict(await build_queue_response(reader))
    except AnalyticsReadError as exc:
        raise _analytics_unavailable(exc) from exc


@router.get("/api/v1/analytics/freshness")
async def get_freshness(reader: Annotated[Any, Depends(get_analytics_reader)]) -> dict[str, Any]:
    try:
        return model_to_dict(await build_freshness_response(reader))
    except AnalyticsReadError as exc:
        raise _analytics_unavailable(exc) from exc


def register_analytics_routes(app: FastAPI) -> None:
    """Register analytics routes directly for this FastAPI version."""
    app.add_api_route("/api/v1/analytics/overview", get_overview, methods=["GET"])
    app.add_api_route("/api/v1/analytics/systems", get_systems, methods=["GET"])
    app.add_api_route("/api/v1/analytics/queue", get_queue, methods=["GET"])
    app.add_api_route("/api/v1/analytics/freshness", get_freshness, methods=["GET"])

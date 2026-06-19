"""Read-only public-applications routes for DF Local Foundation."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request

from app.public_applications_services import (
    PublicApplicationsReadError,
    build_public_applications_response,
)


async def get_public_applications_reader(request: Request) -> Any:
    """Resolve the request-scoped public-applications reader. Overridable in tests."""
    return request.app.state.public_applications_reader


def _public_applications_unavailable(exc: PublicApplicationsReadError) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "status": "unavailable",
            "error_class": "public_applications_read_failure",
            "schema_version": "v1",
        },
    )


async def list_public_applications(
    reader: Annotated[Any, Depends(get_public_applications_reader)],
) -> list[dict[str, Any]]:
    try:
        return await build_public_applications_response(reader)
    except PublicApplicationsReadError as exc:
        raise _public_applications_unavailable(exc) from exc


def register_public_applications_routes(app: FastAPI) -> None:
    """Register public-application routes directly for this FastAPI version."""
    app.add_api_route("/api/v1/public-applications", list_public_applications, methods=["GET"])

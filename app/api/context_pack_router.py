"""Read-only context-pack routes for DF Local Foundation."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request

from app.context_pack_services import (
    ContextPackNotFound,
    ContextPackReadError,
    build_context_pack_response,
)


async def get_context_pack_reader(request: Request) -> Any:
    """Resolve the request-scoped context-pack reader. Overridable in tests."""
    return request.app.state.context_pack_reader


def _context_pack_unavailable(exc: ContextPackReadError) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "status": "unavailable",
            "error_class": "context_pack_read_failure",
            "schema_version": "v1",
        },
    )


async def get_context_pack(
    context_pack_id: str,
    reader: Annotated[Any, Depends(get_context_pack_reader)],
) -> dict[str, Any]:
    try:
        return await build_context_pack_response(reader, context_pack_id)
    except ContextPackNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail=f"context pack {context_pack_id} not found",
        ) from exc
    except ContextPackReadError as exc:
        raise _context_pack_unavailable(exc) from exc


def register_context_pack_routes(app: FastAPI) -> None:
    """Register context-pack routes directly for this FastAPI version."""
    app.add_api_route("/df/rag/context-pack/{context_pack_id}", get_context_pack, methods=["GET"])

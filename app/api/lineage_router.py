"""Read-only lineage routes for DF Local Foundation."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request

from app.lineage_services import (
    LineageNodeNotFound,
    LineageReadError,
    build_lineage_downstream_response,
    build_lineage_node_response,
    build_lineage_nodes_response,
)


async def get_lineage_reader(request: Request) -> Any:
    """Resolve the request-scoped lineage reader. Overridable in tests."""
    return request.app.state.lineage_reader


def _lineage_unavailable(exc: LineageReadError) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "status": "unavailable",
            "error_class": "lineage_read_failure",
            "schema_version": "v1",
        },
    )


async def list_lineage_nodes(
    reader: Annotated[Any, Depends(get_lineage_reader)],
    node_type: str | None = None,
    source_system: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    try:
        return await build_lineage_nodes_response(reader, node_type, source_system, limit)
    except LineageReadError as exc:
        raise _lineage_unavailable(exc) from exc


async def get_lineage_node(
    node_id: str,
    reader: Annotated[Any, Depends(get_lineage_reader)],
) -> dict[str, Any]:
    try:
        return await build_lineage_node_response(reader, node_id)
    except LineageNodeNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail=f"lineage node not found: {node_id}",
        ) from exc
    except LineageReadError as exc:
        raise _lineage_unavailable(exc) from exc


async def get_lineage_downstream(
    node_id: str,
    reader: Annotated[Any, Depends(get_lineage_reader)],
) -> dict[str, Any]:
    try:
        return await build_lineage_downstream_response(reader, node_id)
    except LineageReadError as exc:
        raise _lineage_unavailable(exc) from exc


def register_lineage_routes(app: FastAPI) -> None:
    """Register lineage routes directly for this FastAPI version."""
    app.add_api_route("/api/v1/lineage/nodes", list_lineage_nodes, methods=["GET"])
    app.add_api_route("/api/v1/lineage/nodes/{node_id}", get_lineage_node, methods=["GET"])
    app.add_api_route(
        "/api/v1/lineage/nodes/{node_id}/downstream",
        get_lineage_downstream,
        methods=["GET"],
    )

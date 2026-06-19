"""Read-only proving-slice queue routes for DF Local Foundation."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request

from app.proving_slice_queue_services import (
    ProvingSliceQueueEntryNotFound,
    ProvingSliceQueueReadError,
    build_detail_response,
    build_queue_response,
)


async def get_proving_slice_queue_reader(request: Request) -> Any:
    """Resolve the request-scoped proving-slice queue reader. Overridable in tests."""
    return request.app.state.proving_slice_queue_reader


def _proving_slice_queue_unavailable(exc: ProvingSliceQueueReadError) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "status": "unavailable",
            "error_class": "proving_slice_queue_read_failure",
            "schema_version": "v1",
        },
    )


async def list_proving_slice_queue(
    reader: Annotated[Any, Depends(get_proving_slice_queue_reader)],
    limit: int = 200,
) -> list[dict[str, Any]]:
    try:
        return await build_queue_response(reader, limit)
    except ProvingSliceQueueReadError as exc:
        raise _proving_slice_queue_unavailable(exc) from exc


async def get_proving_slice_queue_detail(
    staged_promotion_id: str,
    reader: Annotated[Any, Depends(get_proving_slice_queue_reader)],
) -> dict[str, Any]:
    try:
        return await build_detail_response(reader, staged_promotion_id)
    except ProvingSliceQueueEntryNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Queue entry not found: {staged_promotion_id}",
        ) from exc
    except ProvingSliceQueueReadError as exc:
        raise _proving_slice_queue_unavailable(exc) from exc


def register_proving_slice_queue_routes(app: FastAPI) -> None:
    """Register proving-slice queue routes directly for this FastAPI version."""
    app.add_api_route("/api/v1/proving-slice/queue", list_proving_slice_queue, methods=["GET"])
    app.add_api_route(
        "/api/v1/proving-slice/queue/{staged_promotion_id}",
        get_proving_slice_queue_detail,
        methods=["GET"],
    )

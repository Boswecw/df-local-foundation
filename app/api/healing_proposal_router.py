"""Read-only healing-proposal routes for DF Local Foundation."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request

from app.healing_proposal_services import (
    HealingProposalNotFound,
    HealingProposalReadError,
    build_healing_proposal_response,
    build_healing_proposals_response,
)


async def get_healing_proposal_reader(request: Request) -> Any:
    """Resolve the request-scoped healing-proposal reader. Overridable in tests."""
    return request.app.state.healing_proposal_reader


def _healing_proposals_unavailable(exc: HealingProposalReadError) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "status": "unavailable",
            "error_class": "healing_proposals_read_failure",
            "schema_version": "v1",
        },
    )


async def list_healing_proposals(
    reader: Annotated[Any, Depends(get_healing_proposal_reader)],
    status: str | None = Query(None),
    repo_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    try:
        return await build_healing_proposals_response(reader, status, repo_id, limit)
    except HealingProposalReadError as exc:
        raise _healing_proposals_unavailable(exc) from exc


async def get_healing_proposal(
    proposal_id: str,
    reader: Annotated[Any, Depends(get_healing_proposal_reader)],
) -> dict[str, Any]:
    try:
        return await build_healing_proposal_response(reader, proposal_id)
    except HealingProposalNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Proposal {proposal_id} not found",
        ) from exc
    except HealingProposalReadError as exc:
        raise _healing_proposals_unavailable(exc) from exc


def register_healing_proposal_routes(app: FastAPI) -> None:
    """Register healing-proposal routes directly for this FastAPI version."""
    app.add_api_route("/api/v1/healing-proposals", list_healing_proposals, methods=["GET"])
    app.add_api_route(
        "/api/v1/healing-proposals/{proposal_id}",
        get_healing_proposal,
        methods=["GET"],
    )

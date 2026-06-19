"""HTTP route tests for DF Local Foundation healing proposals."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.healing_proposal_router import get_healing_proposal_reader
from app.healing_proposal_services import HealingProposalReadError
from app.main import create_app


@asynccontextmanager
async def _noop_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield


class _StubHealingProposalReader:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows
        self.calls: list[tuple[str | None, str | None, int]] = []

    async def fetch_healing_proposal_rows(
        self,
        status: str | None,
        repo_id: str | None,
        limit: int,
    ) -> list[dict]:
        self.calls.append((status, repo_id, limit))
        rows = self._rows
        if status:
            rows = [row for row in rows if row["status"] == status]
        if repo_id:
            rows = [row for row in rows if row["repo_id"] == repo_id]
        return rows[:limit]

    async def fetch_healing_proposal_row(self, proposal_id: str) -> dict | None:
        for row in self._rows:
            if row["proposal_id"] == proposal_id:
                return row
        return None


class _FailingHealingProposalReader:
    async def fetch_healing_proposal_rows(
        self,
        status: str | None,
        repo_id: str | None,
        limit: int,
    ) -> list[dict]:
        raise HealingProposalReadError("test")

    async def fetch_healing_proposal_row(self, proposal_id: str) -> dict | None:
        raise HealingProposalReadError("test")


def _row(
    proposal_id: str = "proposal-001",
    *,
    status: str = "pending",
    repo_id: str = "authorforge",
) -> dict:
    return {
        "proposal_id": proposal_id,
        "source_system": "healing-worker",
        "repo_id": repo_id,
        "commit_sha": "abc123",
        "severity": "info",
        "status": status,
        "schema_version": "LocalEventEnvelope.v1",
        "envelope_json": {"event_id": proposal_id, "repo_id": repo_id},
        "decision_json": None,
        "created_at": datetime(2026, 6, 12, 8, 0, tzinfo=UTC),
    }


def _app_with_reader(reader: object) -> FastAPI:
    app = create_app(lifespan_factory=_noop_lifespan)

    async def _override_reader() -> object:
        return reader

    app.dependency_overrides[get_healing_proposal_reader] = _override_reader
    return app


def test_healing_proposal_routes_are_registered_as_get_only() -> None:
    app = create_app(lifespan_factory=_noop_lifespan)
    routes = {
        getattr(route, "path", ""): getattr(route, "methods", set())
        for route in app.routes
        if getattr(route, "path", "").startswith("/api/v1/healing-proposals")
    }
    assert routes == {
        "/api/v1/healing-proposals": {"GET"},
        "/api/v1/healing-proposals/{proposal_id}": {"GET"},
    }


@pytest.mark.asyncio
async def test_lists_pending_healing_proposals_with_filters() -> None:
    reader = _StubHealingProposalReader(
        [
            _row("proposal-001"),
            _row("proposal-002", status="accepted"),
            _row("proposal-003", repo_id="other"),
        ]
    )
    app = _app_with_reader(reader)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get(
            "/api/v1/healing-proposals",
            params={"status": "pending", "repo_id": "authorforge", "limit": 1},
        )

    assert res.status_code == 200
    assert reader.calls == [("pending", "authorforge", 1)]
    body = res.json()
    assert body["count"] == 1
    assert body["items"][0]["proposal_id"] == "proposal-001"
    assert body["items"][0]["envelope"] == {
        "event_id": "proposal-001",
        "repo_id": "authorforge",
    }
    assert body["items"][0]["created_at"] == "2026-06-12T08:00:00+00:00"


@pytest.mark.asyncio
async def test_get_healing_proposal_returns_source_shape() -> None:
    app = _app_with_reader(_StubHealingProposalReader([_row()]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/v1/healing-proposals/proposal-001")

    assert res.status_code == 200
    body = res.json()
    assert body == {
        "proposal_id": "proposal-001",
        "source_system": "healing-worker",
        "repo_id": "authorforge",
        "commit_sha": "abc123",
        "severity": "info",
        "status": "pending",
        "schema_version": "LocalEventEnvelope.v1",
        "envelope": {"event_id": "proposal-001", "repo_id": "authorforge"},
        "decision": None,
        "created_at": "2026-06-12T08:00:00+00:00",
    }


@pytest.mark.asyncio
async def test_get_missing_healing_proposal_is_404() -> None:
    app = _app_with_reader(_StubHealingProposalReader([]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/v1/healing-proposals/missing")

    assert res.status_code == 404
    assert res.json()["detail"] == "Proposal missing not found"


@pytest.mark.asyncio
async def test_healing_proposal_read_failure_is_explicit_503() -> None:
    app = _app_with_reader(_FailingHealingProposalReader())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        list_res = await client.get("/api/v1/healing-proposals")
        detail_res = await client.get("/api/v1/healing-proposals/proposal-001")

    assert list_res.status_code == 503
    assert detail_res.status_code == 503
    assert list_res.json()["detail"] == {
        "status": "unavailable",
        "error_class": "healing_proposals_read_failure",
        "schema_version": "v1",
    }
    assert detail_res.json()["detail"] == {
        "status": "unavailable",
        "error_class": "healing_proposals_read_failure",
        "schema_version": "v1",
    }

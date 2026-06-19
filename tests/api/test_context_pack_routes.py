"""HTTP route tests for DF Local Foundation context packs."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.context_pack_router import get_context_pack_reader
from app.context_pack_services import ContextPackReadError
from app.main import create_app


@asynccontextmanager
async def _noop_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield


class _StubContextPackReader:
    def __init__(self, rows: dict[str, dict]) -> None:
        self._rows = rows

    async def fetch_context_pack_row(self, context_pack_id: str) -> dict | None:
        return self._rows.get(context_pack_id)


class _FailingContextPackReader:
    async def fetch_context_pack_row(self, context_pack_id: str) -> dict | None:
        raise ContextPackReadError("test")


def _row() -> dict:
    return {
        "context_pack_id": "ctxb_1122676813da3fb5",
        "bundle_hash": "1122676813da3fb5",
        "task_intent_id": "ti_codefix_abc",
        "primary_text": "def add(a, b):\n    return a + b\n",
        "supporting_json": ["def sub(a, b): ...", "# repo nav map"],
        "metadata_json": {"source_classes": ["active_scene", "accepted_lore_record"]},
        "created_at": datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC),
    }


def _app_with_reader(reader: object) -> FastAPI:
    app = create_app(lifespan_factory=_noop_lifespan)

    async def _override_reader() -> object:
        return reader

    app.dependency_overrides[get_context_pack_reader] = _override_reader
    return app


def test_context_pack_route_is_registered_as_get_only() -> None:
    app = create_app(lifespan_factory=_noop_lifespan)
    routes = {
        getattr(route, "path", ""): getattr(route, "methods", set())
        for route in app.routes
        if getattr(route, "path", "") == "/df/rag/context-pack/{context_pack_id}"
    }
    assert routes == {"/df/rag/context-pack/{context_pack_id}": {"GET"}}


@pytest.mark.asyncio
async def test_fetch_pack_returns_neuroforge_read_shape() -> None:
    app = _app_with_reader(_StubContextPackReader({"ctxb_1122676813da3fb5": _row()}))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/df/rag/context-pack/ctxb_1122676813da3fb5")

    assert res.status_code == 200
    body = res.json()
    assert body["primary"] == "def add(a, b):\n    return a + b\n"
    assert body["supporting"] == ["def sub(a, b): ...", "# repo nav map"]
    assert body["metadata"]["context_bundle_id"] == "ctxb_1122676813da3fb5"
    assert body["metadata"]["context_bundle_hash"] == "1122676813da3fb5"
    assert body["metadata"]["task_intent_id"] == "ti_codefix_abc"
    assert body["metadata"]["served_from"] == "precomputed_pact_packet"
    assert body["created_at"] == "2026-06-09T12:00:00+00:00"


@pytest.mark.asyncio
async def test_fetch_missing_pack_is_404() -> None:
    app = _app_with_reader(_StubContextPackReader({}))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/df/rag/context-pack/ctxb_does_not_exist")

    assert res.status_code == 404
    assert res.json()["detail"] == "context pack ctxb_does_not_exist not found"


@pytest.mark.asyncio
async def test_context_pack_read_failure_is_explicit_503() -> None:
    app = _app_with_reader(_FailingContextPackReader())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/df/rag/context-pack/ctxb_1122676813da3fb5")

    assert res.status_code == 503
    assert res.json()["detail"] == {
        "status": "unavailable",
        "error_class": "context_pack_read_failure",
        "schema_version": "v1",
    }

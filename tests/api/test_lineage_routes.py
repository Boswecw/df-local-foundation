"""HTTP route tests for DF Local Foundation lineage reads."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.lineage_router import get_lineage_reader
from app.lineage_services import LineageReadError
from app.main import create_app


@asynccontextmanager
async def _noop_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield


class _StubLineageReader:
    def __init__(
        self,
        node_rows: list[dict],
        edge_rows: list[dict] | None = None,
    ) -> None:
        self._node_rows = node_rows
        self._edge_rows = edge_rows or []
        self.list_calls: list[tuple[str | None, str | None, int]] = []

    async def fetch_lineage_node_rows(
        self,
        node_type: str | None,
        source_system: str | None,
        limit: int,
    ) -> list[dict]:
        self.list_calls.append((node_type, source_system, limit))
        rows = self._node_rows
        if node_type:
            rows = [row for row in rows if row["node_json"]["node_type"] == node_type]
        if source_system:
            rows = [row for row in rows if row["node_json"]["source_system"] == source_system]
        return rows[:limit]

    async def fetch_lineage_node_row(self, node_id: str) -> dict | None:
        for row in self._node_rows:
            if row["node_json"]["node_id"] == node_id:
                return row
        return None

    async def fetch_downstream_edge_rows(self, node_id: str) -> list[dict]:
        return [row for row in self._edge_rows if row["edge_json"]["source_node_id"] == node_id]

    async def fetch_lineage_nodes_by_ids(self, node_ids: list[str]) -> list[dict]:
        node_id_set = set(node_ids)
        return [row for row in self._node_rows if row["node_json"]["node_id"] in node_id_set]


class _FailingLineageReader:
    async def fetch_lineage_node_rows(
        self,
        node_type: str | None,
        source_system: str | None,
        limit: int,
    ) -> list[dict]:
        raise LineageReadError("test")

    async def fetch_lineage_node_row(self, node_id: str) -> dict | None:
        raise LineageReadError("test")

    async def fetch_downstream_edge_rows(self, node_id: str) -> list[dict]:
        raise LineageReadError("test")

    async def fetch_lineage_nodes_by_ids(self, node_ids: list[str]) -> list[dict]:
        raise LineageReadError("test")


def _node(node_id: str, *, node_type: str = "evaluation", source_system: str = "forge_eval") -> dict:
    return {
        "node_json": {
            "schema_version": "LineageNode.v1",
            "node_id": node_id,
            "node_type": node_type,
            "source_system": source_system,
            "payload": {"score": 0.94},
        }
    }


def _edge(edge_id: str, source_node_id: str, target_node_id: str) -> dict:
    return {
        "edge_json": {
            "schema_version": "ImpactEdge.v1",
            "edge_id": edge_id,
            "source_node_id": source_node_id,
            "target_node_id": target_node_id,
            "edge_type": "supports",
        },
        "target_node_id": target_node_id,
    }


def _app_with_reader(reader: object) -> FastAPI:
    app = create_app(lifespan_factory=_noop_lifespan)

    async def _override_reader() -> object:
        return reader

    app.dependency_overrides[get_lineage_reader] = _override_reader
    return app


def test_lineage_routes_are_registered_as_get_only() -> None:
    app = create_app(lifespan_factory=_noop_lifespan)
    routes = {
        getattr(route, "path", ""): getattr(route, "methods", set())
        for route in app.routes
        if getattr(route, "path", "").startswith("/api/v1/lineage/")
    }
    assert routes == {
        "/api/v1/lineage/nodes": {"GET"},
        "/api/v1/lineage/nodes/{node_id}": {"GET"},
        "/api/v1/lineage/nodes/{node_id}/downstream": {"GET"},
    }


@pytest.mark.asyncio
async def test_lists_lineage_nodes_with_source_filters() -> None:
    reader = _StubLineageReader(
        [
            _node("node-001"),
            _node("node-002", source_system="other"),
            _node("node-003", node_type="artifact"),
        ]
    )
    app = _app_with_reader(reader)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get(
            "/api/v1/lineage/nodes",
            params={"node_type": "evaluation", "source_system": "forge_eval", "limit": 1},
        )

    assert res.status_code == 200
    assert reader.list_calls == [("evaluation", "forge_eval", 1)]
    assert res.json() == {"nodes": [_node("node-001")["node_json"]]}


@pytest.mark.asyncio
async def test_get_lineage_node_returns_source_shape() -> None:
    app = _app_with_reader(_StubLineageReader([_node("node-001")]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/v1/lineage/nodes/node-001")

    assert res.status_code == 200
    assert res.json()["node_id"] == "node-001"
    assert res.json()["schema_version"] == "LineageNode.v1"


@pytest.mark.asyncio
async def test_get_missing_lineage_node_is_404() -> None:
    app = _app_with_reader(_StubLineageReader([]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/v1/lineage/nodes/missing")

    assert res.status_code == 404
    assert res.json()["detail"] == "lineage node not found: missing"


@pytest.mark.asyncio
async def test_get_lineage_downstream_returns_edges_and_target_nodes() -> None:
    app = _app_with_reader(
        _StubLineageReader(
            [_node("source"), _node("target", node_type="artifact")],
            [_edge("edge-001", "source", "target")],
        )
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/v1/lineage/nodes/source/downstream")

    assert res.status_code == 200
    assert res.json() == {
        "source_node_id": "source",
        "edges": [_edge("edge-001", "source", "target")["edge_json"]],
        "nodes": [_node("target", node_type="artifact")["node_json"]],
    }


@pytest.mark.asyncio
async def test_lineage_read_failure_is_explicit_503() -> None:
    app = _app_with_reader(_FailingLineageReader())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        list_res = await client.get("/api/v1/lineage/nodes")
        detail_res = await client.get("/api/v1/lineage/nodes/node-001")
        downstream_res = await client.get("/api/v1/lineage/nodes/node-001/downstream")

    expected = {
        "status": "unavailable",
        "error_class": "lineage_read_failure",
        "schema_version": "v1",
    }
    assert list_res.status_code == 503
    assert detail_res.status_code == 503
    assert downstream_res.status_code == 503
    assert list_res.json()["detail"] == expected
    assert detail_res.json()["detail"] == expected
    assert downstream_res.json()["detail"] == expected

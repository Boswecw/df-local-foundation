"""HTTP route tests for DF Local Foundation read-only analytics."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.analytics_services import AnalyticsReadError
from app.api.analytics_router import get_analytics_reader
from app.main import create_app


@asynccontextmanager
async def _noop_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield


class _StubAnalyticsReader:
    def __init__(self, *, services: list[dict] | None = None, queue: list[dict] | None = None) -> None:
        self._services = services or []
        self._queue = queue or []

    async def fetch_system_rows(self) -> list[dict]:
        return self._services

    async def fetch_queue_rows(self) -> list[dict]:
        return self._queue

    async def fetch_freshness_rows(self) -> list[dict]:
        return [
            {
                "service_id": row["service_id"],
                "service_name": row.get("service_name"),
                "last_status_recorded_at": row.get("last_status_recorded_at"),
            }
            for row in self._services
        ]


class _FailingAnalyticsReader:
    async def fetch_system_rows(self) -> list[dict]:
        raise AnalyticsReadError("test")

    async def fetch_queue_rows(self) -> list[dict]:
        raise AnalyticsReadError("test")

    async def fetch_freshness_rows(self) -> list[dict]:
        raise AnalyticsReadError("test")


def _app_with_reader(reader: object) -> FastAPI:
    app = create_app(lifespan_factory=_noop_lifespan)

    async def _override_reader() -> object:
        return reader

    app.dependency_overrides[get_analytics_reader] = _override_reader
    return app


def test_analytics_routes_are_registered_as_get_only() -> None:
    app = create_app(lifespan_factory=_noop_lifespan)
    routes = {
        getattr(route, "path", ""): getattr(route, "methods", set())
        for route in app.routes
        if getattr(route, "path", "").startswith("/api/v1/analytics/")
    }
    assert routes == {
        "/api/v1/analytics/overview": {"GET"},
        "/api/v1/analytics/systems": {"GET"},
        "/api/v1/analytics/queue": {"GET"},
        "/api/v1/analytics/freshness": {"GET"},
    }


@pytest.mark.asyncio
async def test_empty_store_yields_empty_but_valid_payloads() -> None:
    app = _app_with_reader(_StubAnalyticsReader())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        systems_res = await client.get("/api/v1/analytics/systems")
        queue_res = await client.get("/api/v1/analytics/queue")
        overview_res = await client.get("/api/v1/analytics/overview")

    assert systems_res.status_code == 200
    systems = systems_res.json()
    assert systems["_derived"] is True
    assert systems["schema_version"] == "v1"
    assert systems["systems"] == []
    assert systems["staleness_posture"] == "unknown"

    queue = queue_res.json()
    assert queue["status_counts"] == {"queued": 0, "leased": 0, "failed": 0, "deferred": 0}
    assert queue["stale_leases"] == 0
    assert queue["degradation_flags"] == []

    overview = overview_res.json()
    assert overview["systems_summary"]["total_systems"] == 0
    assert overview["queue_summary"]["stale_leases"] == 0
    assert overview["freshness_summary"]["sources_total"] == 0


@pytest.mark.asyncio
async def test_populated_store_computes_live_values() -> None:
    now = datetime.now(UTC)
    services = [
        {
            "service_id": "svc-a",
            "service_name": "Service A",
            "service_state": "ready",
            "readiness_state": "ready",
            "degradation_class": None,
            "last_status_recorded_at": now - timedelta(seconds=10),
        },
        {
            "service_id": "svc-b",
            "service_name": "Service B",
            "service_state": "unavailable",
            "readiness_state": "not_ready",
            "degradation_class": "hard",
            "last_status_recorded_at": now - timedelta(seconds=2000),
        },
    ]
    queue = [
        {"queue_status": "queued", "created_at": now - timedelta(seconds=60), "claim_lease_expires_at": None},
        {
            "queue_status": "claimed_for_send",
            "created_at": now - timedelta(seconds=120),
            "claim_lease_expires_at": now - timedelta(seconds=30),
        },
        {"queue_status": "accepted", "created_at": now - timedelta(seconds=5), "claim_lease_expires_at": None},
    ]
    app = _app_with_reader(_StubAnalyticsReader(services=services, queue=queue))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        systems_res = await client.get("/api/v1/analytics/systems")
        queue_res = await client.get("/api/v1/analytics/queue")
        overview_res = await client.get("/api/v1/analytics/overview")

    systems = systems_res.json()
    by_id = {system["system_id"]: system for system in systems["systems"]}
    assert by_id["svc-a"]["status"] == "healthy"
    assert by_id["svc-a"]["staleness_posture"] == "fresh"
    assert by_id["svc-b"]["status"] == "offline"
    assert by_id["svc-b"]["staleness_posture"] == "stale"

    queue_payload = queue_res.json()
    assert queue_payload["status_counts"] == {"queued": 1, "leased": 1, "failed": 0, "deferred": 0}
    assert queue_payload["stale_leases"] == 1
    assert queue_payload["degradation_flags"] == ["stale_lease_detected"]
    assert queue_payload["oldest_item_age_seconds"] >= 120

    overview = overview_res.json()
    assert overview["systems_summary"] == {
        "total_systems": 2,
        "healthy_systems": 1,
        "degraded_systems": 0,
        "offline_systems": 1,
    }
    assert "offline_system_detected" in overview["degradation_flags"]
    assert "stale_lease_detected" in overview["degradation_flags"]


@pytest.mark.asyncio
async def test_analytics_read_failure_is_explicit_503() -> None:
    app = _app_with_reader(_FailingAnalyticsReader())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/v1/analytics/systems")
    assert res.status_code == 503
    assert res.json()["detail"] == {
        "status": "unavailable",
        "error_class": "analytics_read_failure",
        "schema_version": "v1",
    }

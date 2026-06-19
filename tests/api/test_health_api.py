"""HTTP health API tests.

These exercise the ASGI surface without a database: a no-op lifespan replaces the real one and
`get_reporter` is overridden with a reporter built from a synthetic LifecycleState. This keeps the
test hermetic while still flowing through the real HealthReporter (so the privacy boundary and
contract validation are genuinely exercised).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.main import create_app, get_reporter
from core.config.settings import AppMode
from core.health.reporter import HealthReporter
from core.lifecycle.manager import ErrorClass, LifecycleState, LifecycleStatus

# Fields the foundation contract forbids in any health response (privacy boundary).
BANNED_FIELDS = {
    "table_contents",
    "record_counts",
    "project_names",
    "manuscript_names",
    "domain_metadata",
    "query_surface",
    "table_list",
    "customer_data",
}


@asynccontextmanager
async def _noop_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield


def _state(status: LifecycleStatus, **overrides: object) -> LifecycleState:
    base: dict[str, object] = {
        "status": status,
        "schema_version": "0002",
        "expected_schema_version": "0002",
        "migration_required": False,
        "started_at": datetime.now(UTC),
        "app_mode": AppMode.LOCAL,
    }
    base.update(overrides)
    return LifecycleState(**base)  # type: ignore[arg-type]


def _app_with_reporter(status: LifecycleStatus, **overrides: object) -> FastAPI:
    app = create_app(lifespan_factory=_noop_lifespan)
    response = HealthReporter.from_state(_state(status, **overrides))

    class _StubReporter:
        async def get_health(self) -> object:
            return response

    async def _override_reporter() -> _StubReporter:
        return _StubReporter()

    app.dependency_overrides[get_reporter] = _override_reporter
    return app


@pytest.mark.asyncio
async def test_live_does_not_touch_database() -> None:
    # /live must answer without any reporter/DB dependency.
    app = create_app(lifespan_factory=_noop_lifespan)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/live")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "live"
    assert body["service"] == "df-local-foundation"


@pytest.mark.asyncio
async def test_health_reports_ready() -> None:
    app = _app_with_reporter(LifecycleStatus.READY)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ready"
    assert body["schema_version"] == "0002"
    assert body["migration_required"] is False
    assert body["db_engine"] == "postgresql"


@pytest.mark.asyncio
async def test_health_reports_unavailable_when_db_down() -> None:
    app = _app_with_reporter(
        LifecycleStatus.UNAVAILABLE,
        schema_version="unknown",
        migration_required=True,
        last_error_class=ErrorClass.CONNECTION_FAILURE,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "unavailable"
    assert body["last_error_class"] == "connection_failure"


@pytest.mark.parametrize("status", list(LifecycleStatus))
@pytest.mark.asyncio
async def test_health_never_leaks_domain_fields(status: LifecycleStatus) -> None:
    # The contract: a health response is the maximum control-plane surface — no domain data.
    extra = (
        {"schema_version": "unknown", "migration_required": True}
        if status is LifecycleStatus.UNAVAILABLE
        else {}
    )
    app = _app_with_reporter(status, **extra)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/health")
    assert res.status_code == 200
    assert BANNED_FIELDS.isdisjoint(res.json().keys())

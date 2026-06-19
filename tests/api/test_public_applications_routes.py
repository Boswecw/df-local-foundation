"""HTTP route tests for DF Local Foundation public applications."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.public_applications_router import get_public_applications_reader
from app.main import create_app
from app.public_applications_services import PublicApplicationsReadError


@asynccontextmanager
async def _noop_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield


class _StubPublicApplicationsReader:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    async def fetch_public_application_rows(self) -> list[dict]:
        return self._rows


class _FailingPublicApplicationsReader:
    async def fetch_public_application_rows(self) -> list[dict]:
        raise PublicApplicationsReadError("test")


def _row(name: str, *, is_enabled: bool = True, is_public: bool = True) -> dict:
    return {
        "application_name": name,
        "display_name": name.capitalize(),
        "owns_service_name": "df_local_foundation",
        "ownership_class": "app_local",
        "visibility_class": "operator_safe",
        "forgecustomer_product_ref": name,
        "is_public": is_public,
        "is_enabled": is_enabled,
        "created_at": datetime(2026, 6, 11, 3, 10, tzinfo=UTC),
        "updated_at": datetime(2026, 6, 11, 3, 10, tzinfo=UTC),
    }


def _app_with_reader(reader: object) -> FastAPI:
    app = create_app(lifespan_factory=_noop_lifespan)

    async def _override_reader() -> object:
        return reader

    app.dependency_overrides[get_public_applications_reader] = _override_reader
    return app


def test_public_applications_route_is_registered_as_get_only() -> None:
    app = create_app(lifespan_factory=_noop_lifespan)
    routes = {
        getattr(route, "path", ""): getattr(route, "methods", set())
        for route in app.routes
        if getattr(route, "path", "") == "/api/v1/public-applications"
    }
    assert routes == {"/api/v1/public-applications": {"GET"}}


@pytest.mark.asyncio
async def test_lists_authorforge_with_local_data_ownership() -> None:
    app = _app_with_reader(_StubPublicApplicationsReader([_row("authorforge")]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/v1/public-applications")

    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    app_row = body[0]
    assert app_row["application_name"] == "authorforge"
    assert app_row["owns_service_name"] == "df_local_foundation"
    assert app_row["ownership_class"] == "app_local"
    assert app_row["forgecustomer_product_ref"] == "authorforge"
    assert app_row["created_at"] == "2026-06-11T03:10:00+00:00"


@pytest.mark.asyncio
async def test_non_public_and_disabled_applications_are_excluded() -> None:
    app = _app_with_reader(
        _StubPublicApplicationsReader(
            [
                _row("internal", is_public=False),
                _row("retired", is_enabled=False),
                _row("authorforge"),
            ]
        )
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/v1/public-applications")

    assert res.status_code == 200
    assert [item["application_name"] for item in res.json()] == ["authorforge"]


@pytest.mark.asyncio
async def test_public_applications_read_failure_is_explicit_503() -> None:
    app = _app_with_reader(_FailingPublicApplicationsReader())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/v1/public-applications")

    assert res.status_code == 503
    assert res.json()["detail"] == {
        "status": "unavailable",
        "error_class": "public_applications_read_failure",
        "schema_version": "v1",
    }

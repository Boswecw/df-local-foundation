"""HTTP route tests for DF Local Foundation proving-slice queue reads."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.proving_slice_queue_router import get_proving_slice_queue_reader
from app.main import create_app
from app.proving_slice_queue_services import (
    PS_QUEUE_STATUS_ACCEPTED,
    PS_QUEUE_STATUS_DEAD_LETTERED,
    PS_QUEUE_STATUS_QUEUED,
    ProvingSliceQueueReadError,
)


@asynccontextmanager
async def _noop_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield


class _StubProvingSliceQueueReader:
    def __init__(
        self,
        staging_rows: list[dict],
        artifact_rows: dict[str, dict],
        attempt_rows: dict[str, list[dict]] | None = None,
    ) -> None:
        self._staging_rows = staging_rows
        self._artifact_rows = artifact_rows
        self._attempt_rows = attempt_rows or {}
        self.queue_calls: list[int] = []

    async def fetch_queue_rows(self, limit: int) -> list[dict]:
        self.queue_calls.append(limit)
        rows = [
            {
                **row,
                "payload_json": self._artifact_rows[row["artifact_id"]]["payload_json"],
                "produced_by_system": self._artifact_rows[row["artifact_id"]][
                    "produced_by_system"
                ],
            }
            for row in self._staging_rows
            if row["queue_status"] != PS_QUEUE_STATUS_ACCEPTED
        ]
        rows.sort(key=lambda row: row["updated_at"], reverse=True)
        return rows[:limit]

    async def fetch_detail_rows(self, staged_promotion_id: str) -> tuple[dict | None, dict, list[dict]]:
        for row in self._staging_rows:
            if row["staged_promotion_id"] == staged_promotion_id:
                return (
                    row,
                    self._artifact_rows.get(row["artifact_id"], {}),
                    self._attempt_rows.get(staged_promotion_id, []),
                )
        return None, {}, []


class _FailingProvingSliceQueueReader:
    async def fetch_queue_rows(self, limit: int) -> list[dict]:
        raise ProvingSliceQueueReadError("test")

    async def fetch_detail_rows(self, staged_promotion_id: str) -> tuple[dict | None, dict, list[dict]]:
        raise ProvingSliceQueueReadError("test")


def _now() -> datetime:
    return datetime.now(UTC)


def _staging_row(
    staged_promotion_id: str = "sp-001",
    *,
    artifact_id: str = "artifact-001",
    status: str = PS_QUEUE_STATUS_QUEUED,
    updated_at: datetime | None = None,
) -> dict:
    return {
        "staged_promotion_id": staged_promotion_id,
        "artifact_id": artifact_id,
        "artifact_family": "source_drift_finding",
        "queue_status": status,
        "created_at": _now() - timedelta(minutes=5),
        "updated_at": updated_at if updated_at is not None else _now() - timedelta(seconds=60),
        "promotion_attempt_count": 2,
        "remote_receipt_ref": "receipt-001",
        "last_transport_error": None,
        "last_remote_error_class": None,
        "last_remote_status_code": None,
        "dead_letter_reason": None,
        "claim_lease_owner": None,
        "claim_lease_expires_at": None,
    }


def _artifact_row(*, payload_overrides: dict | None = None) -> dict:
    payload = {
        "system_id": "forge-local",
        "operator_summary": "Schema drift detected in users table",
        "drift_class": "schema_drift",
        "confidence": "high",
        "evidence_refs": ["ref-001"],
        "affected_components": ["users"],
        "detection_source": "contract_check",
        "declared_truth_ref": "users:v1",
        "observed_truth_ref": "users:v2",
    }
    if payload_overrides:
        payload.update(payload_overrides)
    return {"payload_json": payload, "produced_by_system": "DataForge"}


def _app_with_reader(reader: object) -> FastAPI:
    app = create_app(lifespan_factory=_noop_lifespan)

    async def _override_reader() -> object:
        return reader

    app.dependency_overrides[get_proving_slice_queue_reader] = _override_reader
    return app


def test_proving_slice_queue_routes_are_registered_as_get_only() -> None:
    app = create_app(lifespan_factory=_noop_lifespan)
    routes = {
        getattr(route, "path", ""): getattr(route, "methods", set())
        for route in app.routes
        if getattr(route, "path", "").startswith("/api/v1/proving-slice/queue")
    }
    assert routes == {
        "/api/v1/proving-slice/queue": {"GET"},
        "/api/v1/proving-slice/queue/{staged_promotion_id}": {"GET"},
    }


@pytest.mark.asyncio
async def test_lists_non_accepted_queue_rows_in_source_shape() -> None:
    reader = _StubProvingSliceQueueReader(
        [
            _staging_row("sp-001"),
            _staging_row("sp-accepted", artifact_id="artifact-accepted", status=PS_QUEUE_STATUS_ACCEPTED),
        ],
        {
            "artifact-001": _artifact_row(),
            "artifact-accepted": _artifact_row(),
        },
    )
    app = _app_with_reader(reader)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/v1/proving-slice/queue", params={"limit": 1})

    assert res.status_code == 200
    assert reader.queue_calls == [1]
    body = res.json()
    assert len(body) == 1
    row = body[0]
    assert row["staged_promotion_id"] == "sp-001"
    assert row["artifact_id"] == "artifact-001"
    assert row["system_id"] == "forge-local"
    assert row["issue_summary"] == "Schema drift detected in users table"
    assert row["promotion_state"] == PS_QUEUE_STATUS_QUEUED
    assert row["changed_since_last_view"] is True
    assert row["attempt_count"] == 2


@pytest.mark.asyncio
async def test_get_queue_detail_returns_derived_source_shape() -> None:
    attempts = [
        {
            "attempted_at": "2026-04-04T10:02:00",
            "attempt_number": 2,
            "transport_action": "send_and_receive_receipt",
            "outcome_class": "accepted",
            "remote_status_code": 200,
        },
        {
            "attempted_at": "2026-04-04T10:00:00",
            "attempt_number": 1,
            "transport_action": "send_and_receive_receipt",
            "outcome_class": "failed_retryable",
            "remote_status_code": 503,
        },
    ]
    app = _app_with_reader(
        _StubProvingSliceQueueReader(
            [_staging_row()],
            {"artifact-001": _artifact_row()},
            {"sp-001": attempts},
        )
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/v1/proving-slice/queue/sp-001")

    assert res.status_code == 200
    body = res.json()
    assert body["staged_promotion_id"] == "sp-001"
    assert body["artifact_id"] == "artifact-001"
    assert body["summary_header"]["_derived"] is True
    assert body["summary_header"]["issue_title"] == "Schema drift detected in users table"
    assert body["evidence_summary"]["evidence_refs"] == ["ref-001"]
    assert body["promotion_lifecycle_block"]["_derived"] is True
    assert body["promotion_lifecycle_block"]["attempt_count"] == 2
    assert [row["attempt_number"] for row in body["audit_summary"]] == [1, 2]


@pytest.mark.asyncio
async def test_dead_lettered_detail_includes_rejection_block() -> None:
    staging = _staging_row(status=PS_QUEUE_STATUS_DEAD_LETTERED)
    staging["dead_letter_reason"] = "Retry ceiling (5) reached. Last error: timeout."
    staging["last_remote_error_class"] = "timeout"
    app = _app_with_reader(
        _StubProvingSliceQueueReader([staging], {"artifact-001": _artifact_row()})
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/v1/proving-slice/queue/sp-001")

    assert res.status_code == 200
    block = res.json()["rejection_dead_letter_block"]
    assert block["state"] == PS_QUEUE_STATUS_DEAD_LETTERED
    assert block["rejection_class"] == "timeout"
    assert block["retry_allowed"] is False
    assert block["operator_action_required"] is True
    assert block["_derived"] is True


@pytest.mark.asyncio
async def test_get_missing_queue_entry_is_404() -> None:
    app = _app_with_reader(_StubProvingSliceQueueReader([], {}))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/v1/proving-slice/queue/missing")

    assert res.status_code == 404
    assert res.json()["detail"] == "Queue entry not found: missing"


@pytest.mark.asyncio
async def test_proving_slice_queue_read_failure_is_explicit_503() -> None:
    app = _app_with_reader(_FailingProvingSliceQueueReader())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        list_res = await client.get("/api/v1/proving-slice/queue")
        detail_res = await client.get("/api/v1/proving-slice/queue/sp-001")

    expected = {
        "status": "unavailable",
        "error_class": "proving_slice_queue_read_failure",
        "schema_version": "v1",
    }
    assert list_res.status_code == 503
    assert detail_res.status_code == 503
    assert list_res.json()["detail"] == expected
    assert detail_res.json()["detail"] == expected

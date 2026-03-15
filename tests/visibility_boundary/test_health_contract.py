"""Tests: Privacy boundary enforcement on health/status surfaces.

Acceptance criteria:
- No table contents reachable via status/health
- No record counts exposed
- No project or manuscript names reachable
- ForgeCommand-facing artifacts contain only the declared field set
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import pytest

from core.config.settings import AppMode
from core.health.reporter import HealthReporter, HealthResponse, PrivacyViolationError
from core.lifecycle.manager import LifecycleState, LifecycleStatus, ErrorClass


SCHEMA_PATH = Path(__file__).parent.parent.parent / "contracts" / "health.schema.json"
HEALTH_SCHEMA = json.loads(SCHEMA_PATH.read_text())

_STARTED_AT = datetime.now(UTC)


def _ready_state() -> LifecycleState:
    return LifecycleState(
        status=LifecycleStatus.READY,
        schema_version="0002",
        expected_schema_version="0002",
        migration_required=False,
        started_at=_STARTED_AT,
        app_mode=AppMode.LOCAL,
    )


class TestHealthContractShape:
    def test_ready_state_produces_valid_contract(self) -> None:
        state = _ready_state()
        response = HealthReporter.from_state(state)
        d = response.to_dict()
        # Must validate against the JSON schema
        jsonschema.validate(instance=d, schema=HEALTH_SCHEMA)

    def test_all_required_fields_present(self) -> None:
        state = _ready_state()
        response = HealthReporter.from_state(state)
        d = response.to_dict()
        required = {
            "status", "schema_version", "expected_schema_version",
            "migration_required", "started_at", "db_engine",
            "ownership", "app_mode",
        }
        assert required.issubset(d.keys()), f"Missing fields: {required - d.keys()}"

    def test_db_engine_is_always_postgresql(self) -> None:
        state = _ready_state()
        response = HealthReporter.from_state(state)
        assert response.to_dict()["db_engine"] == "postgresql"

    def test_ownership_is_always_app_local(self) -> None:
        state = _ready_state()
        response = HealthReporter.from_state(state)
        assert response.to_dict()["ownership"] == "app-local"

    def test_status_values_are_bounded(self) -> None:
        allowed = {"ready", "degraded", "unavailable", "migrating"}
        for status in LifecycleStatus:
            state = LifecycleState(
                status=status,
                schema_version="0002",
                expected_schema_version="0002",
                migration_required=False,
                started_at=_STARTED_AT,
                app_mode=AppMode.LOCAL,
            )
            response = HealthReporter.from_state(state)
            assert response.to_dict()["status"] in allowed


class TestPrivacyBoundary:
    """These tests prove that banned fields cannot enter the health surface."""

    def test_banned_field_raises_privacy_violation(self) -> None:
        data = {
            "status": "ready",
            "schema_version": "0002",
            "expected_schema_version": "0002",
            "migration_required": False,
            "last_error_class": None,
            "started_at": _STARTED_AT.isoformat(),
            "db_engine": "postgresql",
            "ownership": "app-local",
            "app_mode": "local",
            # BANNED field injected
            "table_contents": [{"id": 1, "manuscript": "Secret Draft"}],
        }
        with pytest.raises(PrivacyViolationError):
            HealthResponse(data)

    def test_record_counts_banned(self) -> None:
        data = {
            "status": "ready",
            "schema_version": "0002",
            "expected_schema_version": "0002",
            "migration_required": False,
            "last_error_class": None,
            "started_at": _STARTED_AT.isoformat(),
            "db_engine": "postgresql",
            "ownership": "app-local",
            "app_mode": "local",
            "record_counts": {"manuscripts": 42},
        }
        with pytest.raises(PrivacyViolationError):
            HealthResponse(data)

    def test_project_names_banned(self) -> None:
        data = {
            "status": "ready",
            "schema_version": "0002",
            "expected_schema_version": "0002",
            "migration_required": False,
            "last_error_class": None,
            "started_at": _STARTED_AT.isoformat(),
            "db_engine": "postgresql",
            "ownership": "app-local",
            "app_mode": "local",
            "project_names": ["My Secret Novel"],
        }
        with pytest.raises(PrivacyViolationError):
            HealthResponse(data)

    def test_customer_data_banned(self) -> None:
        data = {
            "status": "ready",
            "schema_version": "0002",
            "expected_schema_version": "0002",
            "migration_required": False,
            "last_error_class": None,
            "started_at": _STARTED_AT.isoformat(),
            "db_engine": "postgresql",
            "ownership": "app-local",
            "app_mode": "local",
            "customer_data": {"name": "Alice"},
        }
        with pytest.raises(PrivacyViolationError):
            HealthResponse(data)

    def test_valid_health_dict_has_no_extra_fields(self) -> None:
        """Health dict must not contain any fields beyond the contract."""
        state = _ready_state()
        response = HealthReporter.from_state(state)
        d = response.to_dict()
        allowed_keys = {
            "status", "schema_version", "expected_schema_version",
            "migration_required", "last_error_class", "started_at",
            "db_engine", "ownership", "app_mode",
            "backup_available", "last_backup_at", "export_available",
        }
        extra = set(d.keys()) - allowed_keys
        assert not extra, f"Unexpected fields in health response: {extra}"


class TestErrorClassVocabulary:
    """Error classes must use bounded vocabulary — no free-form text."""

    def test_null_error_class_is_valid(self) -> None:
        state = _ready_state()
        response = HealthReporter.from_state(state)
        assert response.to_dict()["last_error_class"] is None

    def test_migration_failure_class_is_valid(self) -> None:
        state = LifecycleState(
            status=LifecycleStatus.UNAVAILABLE,
            schema_version="unknown",
            expected_schema_version="0002",
            migration_required=True,
            started_at=_STARTED_AT,
            app_mode=AppMode.LOCAL,
            last_error_class=ErrorClass.MIGRATION_FAILURE,
        )
        response = HealthReporter.from_state(state)
        d = response.to_dict()
        assert d["last_error_class"] == "migration_failure"
        jsonschema.validate(instance=d, schema=HEALTH_SCHEMA)

    def test_error_class_values_are_schema_bounded(self) -> None:
        """All ErrorClass members must be in the schema enum."""
        allowed = set(HEALTH_SCHEMA["properties"]["last_error_class"]["enum"]) - {None}
        for ec in ErrorClass:
            assert ec.value in allowed, f"ErrorClass.{ec.name} not in schema enum"


class TestMigrationState:
    def test_migrating_state_blocks_ready(self) -> None:
        state = LifecycleState(
            status=LifecycleStatus.MIGRATING,
            schema_version="0001",
            expected_schema_version="0002",
            migration_required=True,
            started_at=_STARTED_AT,
            app_mode=AppMode.LOCAL,
        )
        response = HealthReporter.from_state(state)
        assert not response.is_ready
        assert response.to_dict()["migration_required"] is True

    def test_schema_version_mismatch_sets_migration_required(self) -> None:
        state = LifecycleState(
            status=LifecycleStatus.MIGRATING,
            schema_version="0001",
            expected_schema_version="0002",
            migration_required=True,
            started_at=_STARTED_AT,
            app_mode=AppMode.LOCAL,
        )
        d = HealthReporter.from_state(state).to_dict()
        assert d["migration_required"] is True
        assert d["schema_version"] != d["expected_schema_version"]

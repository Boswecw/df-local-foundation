"""Red-team tests: Status leakage attacks.

These tests ACTIVELY ATTEMPT to leak restricted data through status surfaces.
If the implementation prevents the leak, the test passes.
If not, the test exposes a real hole.

All 11 attack vectors from plan v1.2 section 3.1.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import pytest

from core.health.reporter import HealthResponse, PrivacyViolationError

SCHEMA_PATH = Path(__file__).parent.parent.parent / "contracts" / "health.schema.json"
HEALTH_SCHEMA = json.loads(SCHEMA_PATH.read_text())

_BASE = {
    "status": "ready",
    "schema_version": "0002",
    "expected_schema_version": "0002",
    "migration_required": False,
    "last_error_class": None,
    "started_at": datetime.now(UTC).isoformat(),
    "db_engine": "postgresql",
    "ownership": "app-local",
    "app_mode": "local",
}


def _inject(**extra) -> dict:
    return {**_BASE, **extra}


class TestInjectionAttacks:
    def test_attack_01_record_counts_injection(self) -> None:
        """Attack: inject record_counts into health response."""
        with pytest.raises(PrivacyViolationError):
            HealthResponse(_inject(record_counts={"manuscripts": 42, "projects": 7}))

    def test_attack_02_project_names_injection(self) -> None:
        """Attack: inject project_names into health response."""
        with pytest.raises(PrivacyViolationError):
            HealthResponse(_inject(project_names=["Secret Novel", "Draft 2"]))

    def test_attack_03_manuscript_names_injection(self) -> None:
        """Attack: inject manuscript_names into health response."""
        with pytest.raises(PrivacyViolationError):
            HealthResponse(_inject(manuscript_names=["Chapter 1", "The Prologue"]))

    def test_attack_04_table_list_injection(self) -> None:
        """Attack: inject table_list (schema inventory leak) into health response."""
        with pytest.raises(PrivacyViolationError):
            HealthResponse(_inject(table_list=["authorforge.manuscripts", "authorforge.lore"]))

    def test_attack_05_query_surface_injection(self) -> None:
        """Attack: inject a query_surface endpoint reference into health response."""
        with pytest.raises(PrivacyViolationError):
            HealthResponse(_inject(query_surface="/db/query"))

    def test_attack_06_customer_data_injection(self) -> None:
        """Attack: inject customer_data object into health response."""
        with pytest.raises(PrivacyViolationError):
            HealthResponse(_inject(customer_data={"user": "alice", "email": "alice@example.com"}))

    def test_attack_07_table_contents_injection(self) -> None:
        """Attack: inject table_contents (raw row data) into health response."""
        with pytest.raises(PrivacyViolationError):
            HealthResponse(_inject(table_contents=[{"id": 1, "title": "My Book"}]))

    def test_attack_08_domain_metadata_injection(self) -> None:
        """Attack: inject domain_metadata into health response."""
        with pytest.raises(PrivacyViolationError):
            HealthResponse(_inject(domain_metadata={"genre": "fantasy", "word_count": 80000}))

    def test_attack_09_free_form_error_text_blocked_by_schema(self) -> None:
        """Attack: set last_error_class to free-form text (not in vocabulary)."""
        data = _inject(last_error_class="SQL error: table 'manuscripts' does not exist near col 5")
        with pytest.raises((jsonschema.ValidationError, ValueError)):
            HealthResponse(data)

    def test_attack_10_undeclared_status_value_blocked_by_schema(self) -> None:
        """Attack: set status to a non-vocabulary value."""
        data = _inject(status="operational")
        with pytest.raises((jsonschema.ValidationError, ValueError)):
            HealthResponse(data)

    def test_attack_11_extra_field_blocked_by_schema(self) -> None:
        """Attack: add an arbitrary extra field to slip past additionalProperties."""
        data = _inject(internal_query="SELECT * FROM authorforge.manuscripts")
        # First check: banned field set blocks it
        # If it's not in the banned set, schema additionalProperties:false blocks it
        try:
            response = HealthResponse(data)
            # If HealthResponse was constructed, verify schema blocks it
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate(instance=response.to_dict(), schema=HEALTH_SCHEMA)
        except (PrivacyViolationError, ValueError):
            pass  # Correctly blocked before schema validation


class TestSchemaConstantEnforcement:
    def test_db_engine_must_be_postgresql(self) -> None:
        """db_engine must be const='postgresql' — any other value fails schema."""
        data = _inject(db_engine="mysql")
        with pytest.raises((jsonschema.ValidationError, ValueError)):
            HealthResponse(data)

    def test_ownership_must_be_app_local(self) -> None:
        """ownership must be const='app-local' — any other value fails schema."""
        data = _inject(ownership="cloud")
        with pytest.raises((jsonschema.ValidationError, ValueError)):
            HealthResponse(data)

    def test_app_mode_must_be_bounded(self) -> None:
        """app_mode must be one of local/hybrid/cloud-enabled."""
        data = _inject(app_mode="saas")
        with pytest.raises((jsonschema.ValidationError, ValueError)):
            HealthResponse(data)


class TestErrorClassVocabularyBoundary:
    """Error classes must not expose free-form content."""

    VALID_CLASSES = [
        "migration_failure",
        "connection_failure",
        "integrity_failure",
        "compatibility_failure",
        "startup_failure",
        "restore_blocked",
        None,
    ]

    @pytest.mark.parametrize("error_class", VALID_CLASSES)
    def test_valid_error_class_accepted(self, error_class) -> None:
        data = _inject(last_error_class=error_class)
        response = HealthResponse(data)
        assert response.to_dict()["last_error_class"] == error_class

    @pytest.mark.parametrize("bad_class", [
        "unknown_class",
        "SQL syntax error near 'manuscripts'",
        "AttributeError: 'NoneType' object has no attribute 'id'",
        "Table 'core_app_registry' doesn't exist",
        "",
    ])
    def test_invalid_error_class_blocked(self, bad_class) -> None:
        data = _inject(last_error_class=bad_class)
        with pytest.raises((jsonschema.ValidationError, ValueError)):
            HealthResponse(data)

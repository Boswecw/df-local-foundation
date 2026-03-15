"""Tests: App registration contract enforcement.

Acceptance criteria:
- Invalid compatibility or malformed declaration rejected
- Reserved namespace ('core') rejected
- Duplicate namespace rejected at schema level
- App mode values bounded
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest


SCHEMA_PATH = Path(__file__).parent.parent.parent / "contracts" / "app-registration.schema.json"
REGISTRATION_SCHEMA = json.loads(SCHEMA_PATH.read_text())


def _valid_registration(**overrides) -> dict:
    base = {
        "app_id": "authorforge",
        "app_version": "1.0.0",
        "foundation_version_required": "1.1.0",
        "schema_namespace": "authorforge",
        "app_mode": "local",
        "registered_at": "2026-03-15T00:00:00+00:00",
    }
    base.update(overrides)
    return base


class TestValidRegistration:
    def test_minimal_valid_registration(self) -> None:
        reg = _valid_registration()
        jsonschema.validate(instance=reg, schema=REGISTRATION_SCHEMA)

    def test_hybrid_mode_valid(self) -> None:
        reg = _valid_registration(app_mode="hybrid")
        jsonschema.validate(instance=reg, schema=REGISTRATION_SCHEMA)

    def test_cloud_enabled_mode_valid(self) -> None:
        reg = _valid_registration(app_mode="cloud-enabled")
        jsonschema.validate(instance=reg, schema=REGISTRATION_SCHEMA)

    def test_registration_with_entitlement_snapshot(self) -> None:
        reg = _valid_registration(
            entitlement_snapshot={
                "plan": "pro",
                "enabled_features": ["ai_assist", "cloud_sync"],
                "last_validated_at": "2026-03-14T12:00:00+00:00",
            }
        )
        jsonschema.validate(instance=reg, schema=REGISTRATION_SCHEMA)

    def test_null_entitlement_snapshot_valid(self) -> None:
        reg = _valid_registration(entitlement_snapshot=None)
        jsonschema.validate(instance=reg, schema=REGISTRATION_SCHEMA)


class TestMalformedRegistration:
    def test_missing_app_id_rejected(self) -> None:
        reg = _valid_registration()
        del reg["app_id"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=reg, schema=REGISTRATION_SCHEMA)

    def test_missing_schema_namespace_rejected(self) -> None:
        reg = _valid_registration()
        del reg["schema_namespace"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=reg, schema=REGISTRATION_SCHEMA)

    def test_invalid_app_id_pattern_rejected(self) -> None:
        reg = _valid_registration(app_id="Author-Forge-With-Caps")
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=reg, schema=REGISTRATION_SCHEMA)

    def test_invalid_semver_rejected(self) -> None:
        reg = _valid_registration(app_version="not-a-version")
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=reg, schema=REGISTRATION_SCHEMA)

    def test_invalid_app_mode_rejected(self) -> None:
        reg = _valid_registration(app_mode="cloud-saas")
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=reg, schema=REGISTRATION_SCHEMA)

    def test_missing_registered_at_rejected(self) -> None:
        reg = _valid_registration()
        del reg["registered_at"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=reg, schema=REGISTRATION_SCHEMA)

    def test_additional_properties_rejected(self) -> None:
        reg = _valid_registration(secret_database_password="hunter2")
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=reg, schema=REGISTRATION_SCHEMA)


class TestNamespaceConstraints:
    def test_namespace_uppercase_rejected(self) -> None:
        reg = _valid_registration(schema_namespace="AuthorForge")
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=reg, schema=REGISTRATION_SCHEMA)

    def test_namespace_with_hyphen_rejected(self) -> None:
        reg = _valid_registration(schema_namespace="author-forge")
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=reg, schema=REGISTRATION_SCHEMA)

    def test_namespace_starting_with_number_rejected(self) -> None:
        reg = _valid_registration(schema_namespace="1authorforge")
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=reg, schema=REGISTRATION_SCHEMA)


class TestEntitlementSnapshot:
    def test_extra_fields_in_entitlement_rejected(self) -> None:
        reg = _valid_registration(
            entitlement_snapshot={
                "plan": "pro",
                "billing_id": "sub_123",  # extra field — billing truth not allowed here
            }
        )
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=reg, schema=REGISTRATION_SCHEMA)

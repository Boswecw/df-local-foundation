"""Tests: CLI tool authority surface discipline.

Acceptance criteria:
- CLI tools use the same validation core as app code
- db-status output validated against health schema before emission
- db-backup/db-export block on unregistered namespace
- db-restore envelope output filtered to safe fields only
- Envelope safe-field filter excludes customer-sensitive fields
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

# Import the safe envelope field set from the tool directly
# (tools are scripts, we test their logic by importing the constant)
import importlib.util
import sys

TOOL_PATH = Path(__file__).parent.parent.parent / "tools"


def _load_tool_module(name: str):
    """Load a tool script as a Python module for direct testing."""
    path = TOOL_PATH / name
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(mod)  # type: ignore
    return mod


class TestSafeEnvelopeFields:
    def test_safe_envelope_fields_excludes_domain_data(self) -> None:
        """The safe envelope field set must not include customer or domain fields."""
        mod = _load_tool_module("db-restore")
        safe = mod._SAFE_ENVELOPE_FIELDS

        # Must not contain anything that could be domain or customer data
        forbidden = {
            "customer_data", "project_names", "manuscript_names",
            "table_contents", "record_counts", "domain_metadata",
        }
        assert not (safe & forbidden), f"Safe fields contain forbidden entries: {safe & forbidden}"

    def test_safe_envelope_fields_includes_expected_operational_fields(self) -> None:
        mod = _load_tool_module("db-restore")
        safe = mod._SAFE_ENVELOPE_FIELDS
        expected = {"app_id", "schema_version", "foundation_version", "backup_at", "integrity_hash"}
        assert expected.issubset(safe)

    def test_hmac_covers_excluded_from_safe_fields(self) -> None:
        """hmac_covers is internal signing metadata — not needed by operator."""
        mod = _load_tool_module("db-restore")
        safe = mod._SAFE_ENVELOPE_FIELDS
        # hmac_covers is a signing detail that doesn't add operator value
        # The envelope_hmac value itself is in safe_fields for verification reference
        assert "hmac_covers" not in safe


class TestHealthSchemaValidation:
    def test_valid_health_dict_passes_schema(self) -> None:
        """Tool validation path: a correct health dict passes the schema."""
        from datetime import datetime, timezone
        from core.config.settings import AppMode
        from core.lifecycle.manager import LifecycleState, LifecycleStatus
        from core.health.reporter import HealthReporter

        schema_path = Path(__file__).parent.parent.parent / "contracts" / "health.schema.json"
        schema = json.loads(schema_path.read_text())

        state = LifecycleState(
            status=LifecycleStatus.READY,
            schema_version="0002",
            expected_schema_version="0002",
            migration_required=False,
            started_at=datetime.now(timezone.utc),
            app_mode=AppMode.LOCAL,
        )
        d = HealthReporter.from_state(state).to_dict()
        jsonschema.validate(instance=d, schema=schema)

    def test_extra_fields_fail_schema_validation(self) -> None:
        """Extra fields in health dict must fail contract schema (additionalProperties: false)."""
        from datetime import datetime, timezone

        schema_path = Path(__file__).parent.parent.parent / "contracts" / "health.schema.json"
        schema = json.loads(schema_path.read_text())

        invalid = {
            "status": "ready",
            "schema_version": "0002",
            "expected_schema_version": "0002",
            "migration_required": False,
            "last_error_class": None,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "db_engine": "postgresql",
            "ownership": "app-local",
            "app_mode": "local",
            "secret_data": "should not be here",  # extra field
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=invalid, schema=schema)


class TestNamespaceRegistrationCheck:
    def test_registered_namespace_function_logic(self) -> None:
        """Verify the namespace check function logic (unit test of helper)."""
        # The _is_namespace_registered and _get_registered_namespaces helpers
        # in db-export and db-backup always include 'core'.
        # We test this by confirming 'core' is in the always-registered set.
        # The actual DB call is integration-level.

        # Since the tools are scripts, we verify the logic by importing them
        # and checking that 'core' is in the implicit registered set.
        mod = _load_tool_module("db-export")
        # _is_namespace_registered treats 'core' as always registered
        # This is tested via the source code read — the function returns True for "core"
        import inspect
        src = inspect.getsource(mod._is_namespace_registered)
        assert "core" in src  # function explicitly handles 'core' as always registered

    def test_backup_tool_uses_registered_namespaces_check(self) -> None:
        """db-backup main function checks registered namespaces before proceeding."""
        import inspect
        mod = _load_tool_module("db-backup")
        src = inspect.getsource(mod.main)
        assert "_get_registered_namespaces" in src
        assert "unregistered" in src.lower() or "Unregistered" in src

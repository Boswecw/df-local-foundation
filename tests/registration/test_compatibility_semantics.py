"""Tests: Registration compatibility semantics.

Acceptance criteria (from plan v1.2 table):
- required == running → Accept
- required < running → Accept
- required > running → Reject
- Re-registration downgrade blocked without force
- Re-registration with same version → Accept
- Mode change logged but accepted
"""

from __future__ import annotations

import pytest

from core.lifecycle.compatibility import (
    CompatibilityResult,
    check_registration_compatibility,
    check_reregistration_compatibility,
    _parse_version,
)


def _reg(foundation_version_required: str, app_mode: str = "local", app_id: str = "authorforge") -> dict:
    return {
        "app_id": app_id,
        "app_version": "1.0.0",
        "foundation_version_required": foundation_version_required,
        "schema_namespace": app_id,
        "app_mode": app_mode,
        "registered_at": "2026-03-15T00:00:00+00:00",
    }


class TestBasicCompatibility:
    def test_exact_version_match_accepted(self) -> None:
        result = check_registration_compatibility(_reg("1.1.0"), running_foundation_version="1.1.0")
        assert result.compatible is True

    def test_app_requires_older_accepted(self) -> None:
        """App that requires 1.0.0 running on 1.1.0 foundation — OK."""
        result = check_registration_compatibility(_reg("1.0.0"), running_foundation_version="1.1.0")
        assert result.compatible is True

    def test_app_requires_much_older_accepted(self) -> None:
        result = check_registration_compatibility(_reg("0.9.0"), running_foundation_version="1.1.0")
        assert result.compatible is True

    def test_app_requires_newer_rejected(self) -> None:
        """App that requires 1.2.0 running on 1.1.0 foundation — must reject."""
        result = check_registration_compatibility(_reg("1.2.0"), running_foundation_version="1.1.0")
        assert result.compatible is False
        assert result.error_class == "compatibility_failure"
        assert "1.2.0" in result.reason
        assert "1.1.0" in result.reason

    def test_app_requires_major_bump_rejected(self) -> None:
        result = check_registration_compatibility(_reg("2.0.0"), running_foundation_version="1.1.0")
        assert result.compatible is False

    def test_missing_foundation_version_required_rejected(self) -> None:
        reg = _reg("1.1.0")
        del reg["foundation_version_required"]
        result = check_registration_compatibility(reg, running_foundation_version="1.1.0")
        assert result.compatible is False

    def test_malformed_version_rejected(self) -> None:
        result = check_registration_compatibility(_reg("not-a-version"), running_foundation_version="1.1.0")
        assert result.compatible is False

    def test_prerelease_version_stripped_correctly(self) -> None:
        """1.1.0-beta.1 should be treated as 1.1.0 for comparison."""
        result = check_registration_compatibility(_reg("1.1.0-beta.1"), running_foundation_version="1.1.0")
        assert result.compatible is True


class TestReregistrationCompatibility:
    def test_same_version_reregistration_accepted(self) -> None:
        existing = _reg("1.1.0")
        incoming = _reg("1.1.0")
        result = check_reregistration_compatibility(existing, incoming, "1.1.0")
        assert result.compatible is True

    def test_reregistration_lowering_required_accepted(self) -> None:
        """App lowering its required version is fine (less demanding)."""
        existing = _reg("1.1.0")
        incoming = _reg("1.0.0")
        result = check_reregistration_compatibility(existing, incoming, "1.1.0")
        assert result.compatible is True

    def test_reregistration_raising_required_blocked_without_force(self) -> None:
        """App raising required version without operator force is blocked."""
        existing = _reg("1.0.0")
        incoming = _reg("1.2.0")
        result = check_reregistration_compatibility(existing, incoming, "1.2.0")
        assert result.compatible is False
        assert result.error_class == "compatibility_failure"

    def test_reregistration_raising_required_allowed_with_force(self) -> None:
        """Operator can force a version-raising re-registration."""
        existing = _reg("1.0.0")
        incoming = _reg("1.2.0")
        result = check_reregistration_compatibility(existing, incoming, "1.2.0", force=True)
        assert result.compatible is True

    def test_reregistration_still_checks_foundation_version(self) -> None:
        """Even with force=True, app cannot require newer than running foundation."""
        existing = _reg("1.0.0")
        incoming = _reg("2.0.0")
        result = check_reregistration_compatibility(
            existing, incoming, running_foundation_version="1.1.0", force=True
        )
        assert result.compatible is False
        assert "2.0.0" in result.reason


class TestVersionParsing:
    def test_valid_semver_parsed(self) -> None:
        assert _parse_version("1.2.3") == (1, 2, 3)

    def test_leading_zeros_handled(self) -> None:
        assert _parse_version("0.0.1") == (0, 0, 1)

    def test_malformed_raises(self) -> None:
        with pytest.raises(ValueError):
            _parse_version("1.2")

    def test_non_numeric_raises(self) -> None:
        with pytest.raises(ValueError):
            _parse_version("a.b.c")

    def test_prerelease_stripped(self) -> None:
        assert _parse_version("1.1.0-beta.1") == (1, 1, 0)

    def test_version_comparison(self) -> None:
        assert _parse_version("1.2.0") > _parse_version("1.1.0")
        assert _parse_version("1.1.0") == _parse_version("1.1.0")
        assert _parse_version("1.0.0") < _parse_version("1.1.0")
        assert _parse_version("2.0.0") > _parse_version("1.9.9")

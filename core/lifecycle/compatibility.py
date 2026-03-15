"""DF Local Foundation — Registration compatibility checker.

Enforces version semantics for app registrations.

Rules (from plan v1.2, section 1.4):
┌──────────────────────────────────────────────────────────────────────────┐
│ Scenario                                        │ Behavior               │
├─────────────────────────────────────────────────┼────────────────────────┤
│ app required == running foundation              │ Accept                 │
│ app required < running foundation               │ Accept (older req OK)  │
│ app required > running foundation               │ Reject — too old       │
│ app schema version > foundation core schema     │ Accept (app ahead)     │
│ app schema version < app's own expected_version │ Migrating for this app │
│ Re-registration with incompatible version change│ Reject unless forced   │
└─────────────────────────────────────────────────┴────────────────────────┘
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CompatibilityResult:
    """Result of a compatibility check.

    If compatible=False, the registration must be rejected before any
    runtime operations proceed.
    """
    compatible: bool
    reason: str | None
    error_class: str | None  # from bounded ErrorClass vocabulary

    @classmethod
    def ok(cls) -> "CompatibilityResult":
        return cls(compatible=True, reason=None, error_class=None)

    @classmethod
    def reject(cls, reason: str, error_class: str = "compatibility_failure") -> "CompatibilityResult":
        return cls(compatible=False, reason=reason, error_class=error_class)


def check_registration_compatibility(
    registration: dict[str, Any],
    running_foundation_version: str,
) -> CompatibilityResult:
    """Check whether a registration is compatible with the running foundation.

    Args:
        registration: App registration dict (must contain 'foundation_version_required').
        running_foundation_version: The foundation version string currently running
                                    (e.g., "1.1.0").

    Returns:
        CompatibilityResult — check .compatible before proceeding.
    """
    required_str = registration.get("foundation_version_required")
    if not required_str:
        return CompatibilityResult.reject(
            reason="Registration is missing 'foundation_version_required'.",
        )

    try:
        required = _parse_version(required_str)
        running = _parse_version(running_foundation_version)
    except ValueError as exc:
        return CompatibilityResult.reject(
            reason=f"Cannot parse version: {exc}",
        )

    # App requires a foundation version newer than what is running
    if required > running:
        return CompatibilityResult.reject(
            reason=(
                f"App requires foundation >= {required_str} "
                f"but running version is {running_foundation_version}. "
                "Update the foundation before registering this app."
            ),
        )

    logger.debug(
        "df_local.registration_compatibility_ok",
        required=required_str,
        running=running_foundation_version,
    )
    return CompatibilityResult.ok()


def check_reregistration_compatibility(
    existing: dict[str, Any],
    incoming: dict[str, Any],
    running_foundation_version: str,
    force: bool = False,
) -> CompatibilityResult:
    """Check whether an incoming re-registration is safe.

    A re-registration that raises the required foundation version
    (i.e., app code now needs a newer foundation) is blocked unless
    `force=True` is passed by the operator.

    Args:
        existing: The previously registered app record.
        incoming: The new registration being attempted.
        running_foundation_version: Current foundation version string.
        force: Operator explicit flag to allow version-raising re-registration.

    Returns:
        CompatibilityResult.
    """
    # First check basic compatibility with running foundation
    basic = check_registration_compatibility(incoming, running_foundation_version)
    if not basic.compatible:
        return basic

    # Check if the re-registration raises the required version
    try:
        old_required = _parse_version(existing.get("foundation_version_required", "0.0.0"))
        new_required = _parse_version(incoming.get("foundation_version_required", "0.0.0"))
    except ValueError as exc:
        return CompatibilityResult.reject(
            reason=f"Cannot parse version during re-registration check: {exc}",
        )

    if new_required > old_required and not force:
        return CompatibilityResult.reject(
            reason=(
                f"Re-registration raises foundation_version_required "
                f"from {existing.get('foundation_version_required')} "
                f"to {incoming.get('foundation_version_required')}. "
                "This is a downgrade of compatibility. "
                "Pass force=True (--force in CLI) for explicit operator intent."
            ),
        )

    # Check app mode change is not silent
    old_mode = existing.get("app_mode")
    new_mode = incoming.get("app_mode")
    if old_mode and new_mode and old_mode != new_mode:
        logger.warning(
            "df_local.registration_mode_change",
            app_id=incoming.get("app_id"),
            old_mode=old_mode,
            new_mode=new_mode,
        )
        # Mode changes are allowed but logged — they are an operator declaration, not a secret.

    return CompatibilityResult.ok()


def _parse_version(version_str: str) -> tuple[int, int, int]:
    """Parse a semver string to a comparable tuple.

    Supports "major.minor.patch" with optional pre-release suffix (ignored for comparison).
    """
    # Strip pre-release (e.g., "1.1.0-beta.1" → "1.1.0")
    base = version_str.split("-")[0]
    parts = base.split(".")
    if len(parts) != 3:
        raise ValueError(f"Version '{version_str}' is not in major.minor.patch format.")
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        raise ValueError(f"Version '{version_str}' contains non-integer parts.")

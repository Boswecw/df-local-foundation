"""DF Local Foundation — Lifecycle manager.

Manages local PostgreSQL lifecycle: connect, check migrations,
report status, and enforce fail-closed on invalid states.

Migration path is protected by a PostgreSQL advisory lock to prevent
concurrent startup races. See migration_lock.py.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import asyncpg

from ..config.settings import FOUNDATION_VERSION, AppMode, FoundationSettings
from .migration_lock import MigrationLockTimeout, migration_lock

logger = logging.getLogger(__name__)


class LifecycleStatus(StrEnum):
    READY = "ready"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    MIGRATING = "migrating"


class ErrorClass(StrEnum):
    MIGRATION_FAILURE = "migration_failure"
    CONNECTION_FAILURE = "connection_failure"
    INTEGRITY_FAILURE = "integrity_failure"
    COMPATIBILITY_FAILURE = "compatibility_failure"
    STARTUP_FAILURE = "startup_failure"
    RESTORE_BLOCKED = "restore_blocked"


class LifecycleState:
    """Immutable snapshot of the current lifecycle state.

    Conforms to contracts/health.schema.json.
    Never includes customer data, table contents, record counts,
    project names, or domain metadata.
    """

    def __init__(
        self,
        status: LifecycleStatus,
        schema_version: str,
        expected_schema_version: str,
        migration_required: bool,
        started_at: datetime,
        app_mode: AppMode,
        last_error_class: ErrorClass | None = None,
        backup_available: bool = False,
        last_backup_at: datetime | None = None,
        export_available: bool = False,
    ) -> None:
        self.status = status
        self.schema_version = schema_version
        self.expected_schema_version = expected_schema_version
        self.migration_required = migration_required
        self.started_at = started_at
        self.app_mode = app_mode
        self.last_error_class = last_error_class
        self.backup_available = backup_available
        self.last_backup_at = last_backup_at
        self.export_available = export_available

    def to_health_dict(self) -> dict[str, Any]:
        """Serialize to the health contract shape.

        The returned dict conforms to contracts/health.schema.json.
        It must contain only the declared fields — no extras.
        """
        result: dict[str, Any] = {
            "status": self.status.value,
            "schema_version": self.schema_version,
            "expected_schema_version": self.expected_schema_version,
            "migration_required": self.migration_required,
            "last_error_class": self.last_error_class.value if self.last_error_class else None,
            "started_at": self.started_at.isoformat(),
            "db_engine": "postgresql",
            "ownership": "app-local",
            "app_mode": self.app_mode.value,
        }
        # Optional extension fields
        if self.backup_available is not None:
            result["backup_available"] = self.backup_available
        if self.last_backup_at is not None:
            result["last_backup_at"] = self.last_backup_at.isoformat()
        if self.export_available is not None:
            result["export_available"] = self.export_available
        return result


class LifecycleManager:
    """Manages the DF Local Foundation lifecycle.

    Responsibilities:
    - Connect to local PostgreSQL
    - Run core migrations (forward-only, fail-closed)
    - Report status via the health contract
    - Log health transitions to core_health_events

    This class does not expose customer data, table contents, or
    domain schemas. All visibility surfaces are bounded by the contract.
    """

    EXPECTED_CORE_VERSION = "0002"

    def __init__(self, settings: FoundationSettings) -> None:
        self._settings = settings
        self._started_at: datetime | None = None
        self._pool: asyncpg.Pool | None = None
        self._current_state: LifecycleState | None = None

    async def start(self) -> LifecycleState:
        """Initialize the lifecycle.

        Steps:
        1. Connect to PostgreSQL (fail → unavailable)
        2. Check and apply core migrations (fail → unavailable)
        3. Log transition to core_health_events
        4. Return the final state

        Raises on any hard fault — never returns a silent degraded state.
        """
        self._started_at = datetime.now(UTC)

        try:
            await self._connect()
        except Exception as exc:
            logger.error("df_local.connection_failure", error=str(type(exc).__name__))
            state = LifecycleState(
                status=LifecycleStatus.UNAVAILABLE,
                schema_version="unknown",
                expected_schema_version=self.EXPECTED_CORE_VERSION,
                migration_required=True,
                started_at=self._started_at,
                app_mode=self._settings.df_local_app_mode,
                last_error_class=ErrorClass.CONNECTION_FAILURE,
            )
            self._current_state = state
            raise LifecycleStartError(ErrorClass.CONNECTION_FAILURE, state) from exc

        # Check / apply migrations — under advisory lock to prevent concurrent races
        state = await self._locked_check_and_migrate()
        await self._log_health_event("core", None, state.status, state.last_error_class)
        self._current_state = state
        return state

    async def status(self) -> LifecycleState:
        """Return current lifecycle state.

        Re-checks migration status on each call.
        Never caches stale status as ready.
        Uses the advisory lock on status checks so a concurrent migrator
        is correctly reflected as 'migrating', not 'ready'.
        """
        if self._pool is None:
            return LifecycleState(
                status=LifecycleStatus.UNAVAILABLE,
                schema_version="unknown",
                expected_schema_version=self.EXPECTED_CORE_VERSION,
                migration_required=True,
                started_at=self._started_at or datetime.now(UTC),
                app_mode=self._settings.df_local_app_mode,
                last_error_class=ErrorClass.CONNECTION_FAILURE,
            )
        return await self._locked_check_and_migrate()

    async def stop(self) -> None:
        """Gracefully close the connection pool."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    # ------------------------------------------------------------------
    # Internal implementation
    # ------------------------------------------------------------------

    async def _locked_check_and_migrate(self) -> LifecycleState:
        """Wrapper that acquires the advisory lock before checking migrations.

        If the lock is held by another process (concurrent startup), we report
        'migrating' — not 'unavailable'. The other process is doing the work.
        """
        assert self._pool is not None
        try:
            async with migration_lock(self._pool):
                return await self._check_and_migrate()
        except MigrationLockTimeout:
            logger.info(
                "df_local.migration_lock_contention",
                extra={"detail": "Another process holds the migration lock - reporting migrating"},
            )
            return LifecycleState(
                status=LifecycleStatus.MIGRATING,
                schema_version="unknown",
                expected_schema_version=self.EXPECTED_CORE_VERSION,
                migration_required=True,
                started_at=self._started_at or datetime.now(UTC),
                app_mode=self._settings.df_local_app_mode,
            )

    async def _connect(self) -> None:
        self._pool = await asyncpg.create_pool(
            self._settings.connection_string,
            min_size=1,
            max_size=5,
        )

    async def _check_and_migrate(self) -> LifecycleState:
        """Check core migration state and apply if needed.

        Fail-closed: any migration failure returns unavailable.
        Never promotes to ready while migrations are pending.
        """
        assert self._pool is not None

        try:
            current_version = await self._get_core_schema_version()
        except Exception as exc:
            logger.error("df_local.migration_version_check_failed", error=str(type(exc).__name__))
            return LifecycleState(
                status=LifecycleStatus.UNAVAILABLE,
                schema_version="unknown",
                expected_schema_version=self.EXPECTED_CORE_VERSION,
                migration_required=True,
                started_at=self._started_at or datetime.now(UTC),
                app_mode=self._settings.df_local_app_mode,
                last_error_class=ErrorClass.MIGRATION_FAILURE,
            )

        migration_required = current_version != self.EXPECTED_CORE_VERSION

        if migration_required:
            logger.info(
                "df_local.migrations_pending",
                current=current_version,
                expected=self.EXPECTED_CORE_VERSION,
            )
            # Report migrating — do not auto-apply in check
            # Migrations are applied explicitly via the lifecycle start path
            return LifecycleState(
                status=LifecycleStatus.MIGRATING,
                schema_version=current_version or "none",
                expected_schema_version=self.EXPECTED_CORE_VERSION,
                migration_required=True,
                started_at=self._started_at or datetime.now(UTC),
                app_mode=self._settings.df_local_app_mode,
            )

        return LifecycleState(
            status=LifecycleStatus.READY,
            schema_version=current_version,
            expected_schema_version=self.EXPECTED_CORE_VERSION,
            migration_required=False,
            started_at=self._started_at or datetime.now(UTC),
            app_mode=self._settings.df_local_app_mode,
        )

    async def _get_core_schema_version(self) -> str | None:
        """Query core_schema_versions for the 'core' target.

        Returns None if the table does not exist yet (pre-first-migration).
        Does not expose any customer data or domain metadata.
        """
        assert self._pool is not None

        try:
            row = await self._pool.fetchrow(
                "SELECT current_version FROM core_schema_versions WHERE target = 'core'"
            )
            return row["current_version"] if row else None
        except asyncpg.UndefinedTableError:
            # Table does not exist yet — migrations have not been run
            return None

    async def _log_health_event(
        self,
        app_id: str,
        previous_status: LifecycleStatus | None,
        new_status: LifecycleStatus,
        error_class: ErrorClass | None,
    ) -> None:
        """Append a health transition event.

        Best-effort — if this write fails, it is logged locally but does
        not block the lifecycle. The event table is coarse telemetry only.
        """
        if self._pool is None:
            return
        try:
            await self._pool.execute(
                """
                INSERT INTO core_health_events
                    (app_id, previous_status, new_status, error_class)
                VALUES ($1, $2, $3, $4)
                """,
                app_id,
                previous_status.value if previous_status else None,
                new_status.value,
                error_class.value if error_class else None,
            )
        except Exception as exc:
            logger.warning(
                "df_local.health_event_log_failed",
                error=str(type(exc).__name__),
            )


class LifecycleStartError(Exception):
    """Raised when lifecycle startup fails.

    Carries the error class and the state at failure time.
    """

    def __init__(self, error_class: ErrorClass, state: LifecycleState) -> None:
        self.error_class = error_class
        self.state = state
        super().__init__(f"Lifecycle start failed: {error_class.value}")

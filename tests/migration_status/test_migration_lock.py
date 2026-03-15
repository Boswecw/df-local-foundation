"""Tests: Migration advisory lock behavior.

Acceptance criteria:
- Lock contention reports 'migrating', not 'unavailable'
- Lock is released after context exits (including on exception)
- Lock timeout is bounded and predictable
- Only one migrator advances at a time (simulated)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.lifecycle.migration_lock import (
    MIGRATION_ADVISORY_LOCK_ID,
    MigrationLockError,
    MigrationLockTimeout,
    migration_lock,
)
from core.lifecycle.manager import (
    ErrorClass,
    LifecycleManager,
    LifecycleStatus,
)
from core.config.settings import AppMode, FoundationSettings


def _make_settings() -> FoundationSettings:
    return FoundationSettings(
        df_local_db="testdb",
        df_local_user="testuser",
        df_local_password="testpass",
        df_local_app_id="authorforge",
    )


class TestMigrationLockTimeout:
    @pytest.mark.asyncio
    async def test_lock_contention_raises_timeout(self) -> None:
        """When lock is held, MigrationLockTimeout is raised after timeout."""
        mock_conn = AsyncMock()
        # pg_try_advisory_lock always returns False (lock held elsewhere)
        mock_conn.fetchval = AsyncMock(return_value=False)

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(MigrationLockTimeout):
            async with migration_lock(mock_pool, timeout_seconds=0.2):
                pass  # Should never reach here

    @pytest.mark.asyncio
    async def test_lock_contention_reports_migrating_not_unavailable(self) -> None:
        """LifecycleManager treats lock contention as 'migrating', not a fault."""
        settings = _make_settings()
        manager = LifecycleManager(settings)

        # Simulate a connected pool that cannot acquire the migration lock
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=False)  # lock always held
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        manager._pool = mock_pool
        manager._started_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)

        state = await manager._locked_check_and_migrate()

        assert state.status == LifecycleStatus.MIGRATING
        assert state.last_error_class is None  # lock contention is not an error class


class TestMigrationLockAcquireRelease:
    @pytest.mark.asyncio
    async def test_lock_acquired_and_released_on_success(self) -> None:
        """Lock is released after successful context block."""
        mock_conn = AsyncMock()
        acquired_calls = []
        released_calls = []

        async def mock_fetchval(query: str, *args):
            if "pg_try_advisory_lock" in query:
                acquired_calls.append(args)
                return True
            return None

        async def mock_execute(query: str, *args):
            if "pg_advisory_unlock" in query:
                released_calls.append(args)

        mock_conn.fetchval = mock_fetchval
        mock_conn.execute = mock_execute

        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        async with migration_lock(mock_pool):
            pass  # body executes

        assert len(acquired_calls) == 1
        assert len(released_calls) == 1

    @pytest.mark.asyncio
    async def test_lock_released_on_exception(self) -> None:
        """Lock is released even when the body raises an exception."""
        mock_conn = AsyncMock()
        released_calls = []

        async def mock_fetchval(query: str, *args):
            if "pg_try_advisory_lock" in query:
                return True
            return None

        async def mock_execute(query: str, *args):
            if "pg_advisory_unlock" in query:
                released_calls.append(args)

        mock_conn.fetchval = mock_fetchval
        mock_conn.execute = mock_execute

        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(ValueError):
            async with migration_lock(mock_pool):
                raise ValueError("body raised")

        assert len(released_calls) == 1


class TestMigrationLockLockId:
    def test_lock_id_is_stable_and_documented(self) -> None:
        """The advisory lock ID must be a stable, documented constant."""
        assert MIGRATION_ADVISORY_LOCK_ID == 454_989_609
        assert isinstance(MIGRATION_ADVISORY_LOCK_ID, int)
        # Must fit in a PostgreSQL bigint
        assert 0 < MIGRATION_ADVISORY_LOCK_ID < 2**63

    @pytest.mark.asyncio
    async def test_lock_uses_documented_id_by_default(self) -> None:
        """migration_lock() uses MIGRATION_ADVISORY_LOCK_ID by default."""
        used_ids = []

        mock_conn = AsyncMock()

        async def mock_fetchval(query: str, lock_id: int):
            if "pg_try_advisory_lock" in query:
                used_ids.append(lock_id)
                return True
            return None

        mock_conn.fetchval = mock_fetchval
        mock_conn.execute = AsyncMock()

        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        async with migration_lock(mock_pool):
            pass

        assert used_ids == [MIGRATION_ADVISORY_LOCK_ID]

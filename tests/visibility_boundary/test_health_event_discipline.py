"""Tests: Health-event retention discipline.

Acceptance criteria:
- Prune does not touch recent events (< MINIMUM_PRUNE_DAYS)
- Prune removes only old events
- MaintenanceError raised for aggressive prune windows
- Prune touches only core_health_events, not app tables
"""

from __future__ import annotations

import pytest

from core.lifecycle.maintenance import (
    MINIMUM_PRUNE_DAYS,
    DEFAULT_RETENTION_DAYS,
    MaintenanceError,
    prune_health_events,
    prune_backup_log,
)


class TestPruneWindowEnforcement:
    @pytest.mark.asyncio
    async def test_prune_below_minimum_blocked(self) -> None:
        """Pruning events newer than MINIMUM_PRUNE_DAYS must be blocked."""
        from unittest.mock import AsyncMock
        pool = AsyncMock()

        with pytest.raises(MaintenanceError) as exc_info:
            await prune_health_events(pool, older_than_days=MINIMUM_PRUNE_DAYS - 1)

        assert "Cannot prune" in str(exc_info.value)
        # Pool must not have been called — the block happens before any DB operation
        pool.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_prune_zero_days_blocked(self) -> None:
        """Pruning with 0 days must be blocked."""
        from unittest.mock import AsyncMock
        pool = AsyncMock()

        with pytest.raises(MaintenanceError):
            await prune_health_events(pool, older_than_days=0)

        pool.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_prune_at_minimum_days_allowed(self) -> None:
        """Pruning exactly at MINIMUM_PRUNE_DAYS is allowed."""
        from unittest.mock import AsyncMock
        pool = AsyncMock()
        pool.execute = AsyncMock(return_value="DELETE 5")

        result = await prune_health_events(pool, older_than_days=MINIMUM_PRUNE_DAYS)

        pool.execute.assert_called_once()
        assert result.rows_pruned == 5
        assert result.table == "core_health_events"

    @pytest.mark.asyncio
    async def test_prune_default_retention_allowed(self) -> None:
        """Default retention window (30 days) must be allowed."""
        from unittest.mock import AsyncMock
        pool = AsyncMock()
        pool.execute = AsyncMock(return_value="DELETE 0")

        result = await prune_health_events(pool, older_than_days=DEFAULT_RETENTION_DAYS)

        pool.execute.assert_called_once()
        assert result.table == "core_health_events"


class TestPruneQueryScope:
    @pytest.mark.asyncio
    async def test_prune_targets_only_health_events_table(self) -> None:
        """Prune must only touch core_health_events, not any other table."""
        from unittest.mock import AsyncMock, call
        pool = AsyncMock()
        pool.execute = AsyncMock(return_value="DELETE 0")

        await prune_health_events(pool, older_than_days=30)

        call_args = pool.execute.call_args
        query: str = call_args[0][0]
        assert "core_health_events" in query
        # Must not reference any app table or domain table
        assert "authorforge" not in query
        assert "manuscript" not in query
        assert "project" not in query

    @pytest.mark.asyncio
    async def test_backup_log_prune_targets_only_backup_table(self) -> None:
        """Backup log prune must only touch core_backup_log."""
        from unittest.mock import AsyncMock
        pool = AsyncMock()
        pool.execute = AsyncMock(return_value="DELETE 2")

        result = await prune_backup_log(pool, older_than_days=30)

        call_args = pool.execute.call_args
        query: str = call_args[0][0]
        assert "core_backup_log" in query
        assert result.table == "core_backup_log"


class TestPruneReturnValue:
    @pytest.mark.asyncio
    async def test_prune_returns_correct_count(self) -> None:
        from unittest.mock import AsyncMock
        pool = AsyncMock()
        pool.execute = AsyncMock(return_value="DELETE 17")

        result = await prune_health_events(pool, older_than_days=30)
        assert result.rows_pruned == 17

    @pytest.mark.asyncio
    async def test_prune_zero_rows_is_not_an_error(self) -> None:
        from unittest.mock import AsyncMock
        pool = AsyncMock()
        pool.execute = AsyncMock(return_value="DELETE 0")

        result = await prune_health_events(pool, older_than_days=30)
        assert result.rows_pruned == 0

    @pytest.mark.asyncio
    async def test_prune_returns_cutoff_timestamp(self) -> None:
        from datetime import datetime, timezone, timedelta
        from unittest.mock import AsyncMock
        pool = AsyncMock()
        pool.execute = AsyncMock(return_value="DELETE 0")

        result = await prune_health_events(pool, older_than_days=30)

        # Cutoff should be approximately 30 days ago
        now = datetime.now(timezone.utc)
        expected_cutoff = now - timedelta(days=30)
        delta = abs((result.cutoff - expected_cutoff).total_seconds())
        assert delta < 5  # within 5 seconds

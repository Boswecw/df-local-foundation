"""DF Local Foundation — Maintenance helpers.

Provides controlled pruning of operational tables.

Rules:
- Retention window: 30 days (default). Older events are prunable.
- Prune is an explicit operator action, not a background process.
- Prune touches only coarse operational tables — never app domain tables.
- Prune does not delete recent events. If older_than_days=0, it is blocked.
- All prune operations are logged.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import asyncpg

logger = logging.getLogger(__name__)

# Default retention window. Older events are candidates for pruning.
DEFAULT_RETENTION_DAYS = 30
# Minimum pruning window. Operators cannot prune events newer than this.
MINIMUM_PRUNE_DAYS = 7


@dataclass
class PruneResult:
    table: str
    rows_pruned: int
    cutoff: datetime


class MaintenanceError(Exception):
    """Raised when a maintenance operation violates safety rules."""
    pass


async def prune_health_events(
    pool: asyncpg.Pool,
    older_than_days: int = DEFAULT_RETENTION_DAYS,
) -> PruneResult:
    """Prune health events older than the given number of days.

    Safety rules:
    - `older_than_days` must be >= MINIMUM_PRUNE_DAYS (7). Pruning recent
      events is blocked to prevent accidental loss of operationally relevant state.
    - This function touches only `core_health_events`. It never touches app tables.
    - Returns count of pruned rows for operator visibility.

    Args:
        pool: asyncpg connection pool.
        older_than_days: Events older than this many days are deleted.

    Returns:
        PruneResult with table name, row count, and cutoff timestamp.

    Raises:
        MaintenanceError: If the requested prune window is too aggressive.
    """
    if older_than_days < MINIMUM_PRUNE_DAYS:
        raise MaintenanceError(
            f"Cannot prune health events newer than {MINIMUM_PRUNE_DAYS} days. "
            f"Requested: {older_than_days} days. "
            "Pruning recent events could hide active operational faults."
        )

    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)

    result = await pool.execute(
        "DELETE FROM core_health_events WHERE occurred_at < $1",
        cutoff,
    )

    # asyncpg returns "DELETE N" as the status string
    rows_pruned = _parse_delete_count(result)

    logger.info(
        "df_local.health_events_pruned",
        rows=rows_pruned,
        older_than_days=older_than_days,
        cutoff=cutoff.isoformat(),
    )

    return PruneResult(
        table="core_health_events",
        rows_pruned=rows_pruned,
        cutoff=cutoff,
    )


async def prune_backup_log(
    pool: asyncpg.Pool,
    older_than_days: int = DEFAULT_RETENTION_DAYS,
) -> PruneResult:
    """Prune backup log entries older than the given number of days.

    Note: This prunes log *records* only — not the backup files themselves.
    Backup files are the operator's responsibility.

    Args:
        pool: asyncpg connection pool.
        older_than_days: Log entries older than this many days are deleted.

    Returns:
        PruneResult with table name, row count, and cutoff timestamp.

    Raises:
        MaintenanceError: If the requested prune window is too aggressive.
    """
    if older_than_days < MINIMUM_PRUNE_DAYS:
        raise MaintenanceError(
            f"Cannot prune backup log entries newer than {MINIMUM_PRUNE_DAYS} days. "
            f"Requested: {older_than_days} days."
        )

    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)

    result = await pool.execute(
        "DELETE FROM core_backup_log WHERE backup_at < $1",
        cutoff,
    )
    rows_pruned = _parse_delete_count(result)

    logger.info(
        "df_local.backup_log_pruned",
        rows=rows_pruned,
        older_than_days=older_than_days,
        cutoff=cutoff.isoformat(),
    )

    return PruneResult(
        table="core_backup_log",
        rows_pruned=rows_pruned,
        cutoff=cutoff,
    )


def _parse_delete_count(status: str) -> int:
    """Parse asyncpg DELETE result status string ('DELETE N') to int."""
    try:
        return int(status.split()[-1])
    except (ValueError, IndexError):
        return 0

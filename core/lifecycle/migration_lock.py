"""DF Local Foundation — Migration advisory lock.

Uses PostgreSQL session-level advisory locks to ensure only one process
can check or advance migration state at a time.

Rules:
- Lock is acquired before any migration check or application.
- Lock is session-scoped: auto-released on connection close.
- If lock cannot be acquired within timeout: caller reports 'migrating', not 'unavailable'.
- No Python-level locking — PostgreSQL is the authority.
- The lock ID is stable and unique to DF Local Foundation across installs.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import asyncpg

logger = logging.getLogger(__name__)

# Stable advisory lock ID for DF Local Foundation migration gate.
# Chosen to be unique and not clash with application-level locks.
# Value: crc32("df-local-foundation-migration") = 0x1B109B29 = 454,989,609
MIGRATION_ADVISORY_LOCK_ID = 454_989_609

# Default timeout waiting for the advisory lock (seconds).
# After this, the caller should report 'migrating', not block indefinitely.
DEFAULT_LOCK_TIMEOUT_SECONDS = 5.0


class MigrationLockTimeout(Exception):
    """Raised when the advisory lock cannot be acquired within the timeout.

    Callers should treat this as a 'migrating' state, not a fault.
    Another process holds the lock and is likely running migrations.
    """
    pass


class MigrationLockError(Exception):
    """Raised when the advisory lock fails for a reason other than timeout."""
    pass


@asynccontextmanager
async def migration_lock(
    pool: asyncpg.Pool,
    lock_id: int = MIGRATION_ADVISORY_LOCK_ID,
    timeout_seconds: float = DEFAULT_LOCK_TIMEOUT_SECONDS,
) -> AsyncIterator[None]:
    """Acquire a PostgreSQL session advisory lock for migration operations.

    Usage:
        try:
            async with migration_lock(pool):
                # safe to check and apply migrations here
                pass
        except MigrationLockTimeout:
            # another process is migrating — report 'migrating' status
            ...

    The lock is:
    - Session-scoped: released automatically on connection close or exception.
    - Non-reentrant: if the same session tries to acquire twice, it succeeds
      (PostgreSQL advisory locks are reentrant per session). This is fine for
      our single-process-per-session model.
    - Timeout-bounded: if the lock is not acquired within `timeout_seconds`,
      MigrationLockTimeout is raised.

    Args:
        pool: asyncpg connection pool.
        lock_id: Advisory lock integer ID.
        timeout_seconds: How long to wait for the lock before giving up.

    Raises:
        MigrationLockTimeout: Lock not acquired within timeout.
        MigrationLockError: Lock acquisition failed for another reason.
    """
    async with pool.acquire() as conn:
        acquired = await _try_acquire_lock(conn, lock_id, timeout_seconds)
        if not acquired:
            raise MigrationLockTimeout(
                f"Could not acquire migration advisory lock (id={lock_id}) "
                f"within {timeout_seconds}s. Another process may be migrating."
            )
        logger.debug("df_local.migration_lock_acquired", lock_id=lock_id)
        try:
            yield
        finally:
            await _release_lock(conn, lock_id)
            logger.debug("df_local.migration_lock_released", lock_id=lock_id)


async def _try_acquire_lock(
    conn: asyncpg.Connection,
    lock_id: int,
    timeout_seconds: float,
) -> bool:
    """Attempt to acquire the advisory lock with a polling loop.

    PostgreSQL's `pg_try_advisory_lock` is non-blocking — it returns false
    immediately if the lock is held. We poll until timeout rather than using
    `pg_advisory_lock` (which blocks indefinitely) to keep lifecycle startup
    predictable.

    Returns True if acquired, False if timeout exceeded.
    """
    deadline = asyncio.get_event_loop().time() + timeout_seconds
    poll_interval = 0.1  # seconds between attempts

    while True:
        try:
            acquired: bool = await conn.fetchval(
                "SELECT pg_try_advisory_lock($1)", lock_id
            )
        except Exception as exc:
            raise MigrationLockError(
                f"Advisory lock query failed: {type(exc).__name__}"
            ) from exc

        if acquired:
            return True

        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            return False

        await asyncio.sleep(min(poll_interval, remaining))


async def _release_lock(conn: asyncpg.Connection, lock_id: int) -> None:
    """Release the advisory lock. Best-effort — connection close also releases it."""
    try:
        await conn.execute("SELECT pg_advisory_unlock($1)", lock_id)
    except Exception as exc:
        # Connection may already be closed — lock will be released with session.
        logger.warning(
            "df_local.migration_lock_release_failed",
            lock_id=lock_id,
            error=str(type(exc).__name__),
        )

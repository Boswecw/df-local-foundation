"""Configuration hooks for DF Local Foundation read-only analytics."""

from __future__ import annotations

import os


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# Master switch. Routes stay mounted regardless; reserved for future gating.
ANALYTICS_ENABLED = _bool_env("DATAFORGE_LOCAL_ANALYTICS_ENABLED", True)

# Staleness posture thresholds (seconds), applied to a source/system age:
#   age < AGING            -> fresh
#   AGING <= age < STALE   -> aging
#   age >= STALE           -> stale
#   age unknown            -> unknown
FRESHNESS_AGING_THRESHOLD_SECONDS = _int_env(
    "DATAFORGE_LOCAL_ANALYTICS_AGING_SECONDS", 300
)
FRESHNESS_STALE_THRESHOLD_SECONDS = _int_env(
    "DATAFORGE_LOCAL_ANALYTICS_STALE_SECONDS", 900
)

# A `claimed_for_send` lease is counted stale once its expiry has passed by this
# grace window (seconds). 0 means "stale the moment the lease expires".
QUEUE_STALE_LEASE_GRACE_SECONDS = _int_env(
    "DATAFORGE_LOCAL_ANALYTICS_STALE_LEASE_GRACE_SECONDS", 0
)

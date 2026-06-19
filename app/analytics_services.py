"""Read-only analytics services for DF Local Foundation.

The source local-system analytics runtime is SQLAlchemy-backed. The app-support
foundation is asyncpg-backed, so this module keeps the source response contract
and pure compute semantics while adapting the read boundary to the support app.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from app.analytics_config import (
    FRESHNESS_AGING_THRESHOLD_SECONDS,
    FRESHNESS_STALE_THRESHOLD_SECONDS,
    QUEUE_STALE_LEASE_GRACE_SECONDS,
)
from app.analytics_models import (
    FreshnessResponse,
    FreshnessSource,
    FreshnessSummary,
    OverviewResponse,
    QueueResponse,
    QueueStatusCounts,
    QueueSummary,
    StalenessPosture,
    SystemEntry,
    SystemsResponse,
    SystemsSummary,
    SystemStatus,
)

logger = logging.getLogger(__name__)

SERVICE_STATE_READY = "ready"
SERVICE_STATE_DEGRADED = "degraded"
SERVICE_STATE_MIGRATING = "migrating"
SERVICE_STATE_UNAVAILABLE = "unavailable"
SERVICE_STATE_UNKNOWN = "unknown"

PS_QUEUE_STATUS_STAGED = "staged"
PS_QUEUE_STATUS_QUEUED = "queued"
PS_QUEUE_STATUS_CLAIMED_FOR_SEND = "claimed_for_send"
PS_QUEUE_STATUS_SEND_FAILED_RETRYABLE = "send_failed_retryable"
PS_QUEUE_STATUS_AWAITING_RECEIPT_RECONCILIATION = "awaiting_receipt_reconciliation"
PS_QUEUE_STATUS_ACCEPTED = "accepted"
PS_QUEUE_STATUS_REJECTED = "rejected"
PS_QUEUE_STATUS_DEAD_LETTERED = "dead_lettered"
PS_QUEUE_TERMINAL_STATUSES = frozenset(
    {
        PS_QUEUE_STATUS_ACCEPTED,
        PS_QUEUE_STATUS_REJECTED,
        PS_QUEUE_STATUS_DEAD_LETTERED,
    }
)

_SERVICE_STATE_TO_STATUS: dict[str, SystemStatus] = {
    SERVICE_STATE_READY: SystemStatus.HEALTHY,
    SERVICE_STATE_DEGRADED: SystemStatus.DEGRADED,
    SERVICE_STATE_MIGRATING: SystemStatus.DEGRADED,
    SERVICE_STATE_UNAVAILABLE: SystemStatus.OFFLINE,
    SERVICE_STATE_UNKNOWN: SystemStatus.UNKNOWN,
}

_QUEUE_STATUS_TO_BUCKET: dict[str, str] = {
    PS_QUEUE_STATUS_STAGED: "queued",
    PS_QUEUE_STATUS_QUEUED: "queued",
    PS_QUEUE_STATUS_CLAIMED_FOR_SEND: "leased",
    PS_QUEUE_STATUS_AWAITING_RECEIPT_RECONCILIATION: "leased",
    PS_QUEUE_STATUS_SEND_FAILED_RETRYABLE: "failed",
    PS_QUEUE_STATUS_REJECTED: "deferred",
    PS_QUEUE_STATUS_DEAD_LETTERED: "deferred",
}

_SYSTEMS_SQL = """
    SELECT r.service_id,
           r.service_name,
           c.service_state,
           c.readiness_state,
           c.degradation_class,
           c.last_status_recorded_at
    FROM service_registry.registered_services r
    LEFT JOIN service_status.service_status_current c
      ON c.service_id = r.service_id
    WHERE r.is_enabled = true
    ORDER BY r.service_name
"""

_QUEUE_SQL = """
    SELECT queue_status, created_at, claim_lease_expires_at
    FROM runtime_promotion.ps_promotion_staging
"""

_FRESHNESS_SQL = """
    SELECT r.service_id,
           r.service_name,
           c.last_status_recorded_at
    FROM service_registry.registered_services r
    LEFT JOIN service_status.service_status_current c
      ON c.service_id = r.service_id
    WHERE r.is_enabled = true
    ORDER BY r.service_name
"""


class AnalyticsReadError(RuntimeError):
    """Raised when the support foundation cannot read analytics source tables."""


class AnalyticsReader(Protocol):
    async def fetch_system_rows(self) -> list[dict[str, Any]]:
        """Fetch enabled service status rows."""

    async def fetch_queue_rows(self) -> list[dict[str, Any]]:
        """Fetch promotion queue rows."""

    async def fetch_freshness_rows(self) -> list[dict[str, Any]]:
        """Fetch per-service freshness rows."""


class AsyncpgAnalyticsReader:
    """Asyncpg-backed analytics reader for the support foundation."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    async def fetch_system_rows(self) -> list[dict[str, Any]]:
        return await self._fetch(_SYSTEMS_SQL)

    async def fetch_queue_rows(self) -> list[dict[str, Any]]:
        return await self._fetch(_QUEUE_SQL)

    async def fetch_freshness_rows(self) -> list[dict[str, Any]]:
        return await self._fetch(_FRESHNESS_SQL)

    async def _fetch(self, sql: str) -> list[dict[str, Any]]:
        import asyncpg

        try:
            conn = await asyncpg.connect(self._dsn)
            try:
                return [dict(row) for row in await conn.fetch(sql)]
            finally:
                await conn.close()
        except Exception as exc:
            logger.warning("df_local.analytics_read_failed error=%s", type(exc).__name__)
            raise AnalyticsReadError("analytics_read_failed") from exc


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _as_utc(value).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _age_seconds(now: datetime, value: datetime | None) -> int | None:
    if value is None:
        return None
    return max(0, int((now - _as_utc(value)).total_seconds()))


def _posture_for_age(age_seconds: int | None) -> StalenessPosture:
    if age_seconds is None:
        return StalenessPosture.UNKNOWN
    if age_seconds < FRESHNESS_AGING_THRESHOLD_SECONDS:
        return StalenessPosture.FRESH
    if age_seconds < FRESHNESS_STALE_THRESHOLD_SECONDS:
        return StalenessPosture.AGING
    return StalenessPosture.STALE


def _overall_posture(postures: list[StalenessPosture]) -> StalenessPosture:
    """Least-fresh wins; all-unknown or empty collapses to unknown."""
    seen = set(postures)
    if StalenessPosture.STALE in seen:
        return StalenessPosture.STALE
    if StalenessPosture.AGING in seen:
        return StalenessPosture.AGING
    if StalenessPosture.FRESH in seen:
        return StalenessPosture.FRESH
    return StalenessPosture.UNKNOWN


def compute_systems_response(rows: list[dict[str, Any]], now: datetime) -> SystemsResponse:
    systems: list[SystemEntry] = []
    for row in rows:
        age = _age_seconds(now, row.get("last_status_recorded_at"))
        state = row.get("service_state") or SERVICE_STATE_UNKNOWN
        systems.append(
            SystemEntry(
                system_id=str(row["service_id"]),
                system_name=row.get("service_name") or str(row["service_id"]),
                status=_SERVICE_STATE_TO_STATUS.get(state, SystemStatus.UNKNOWN),
                staleness_posture=_posture_for_age(age),
                last_success_at=_iso(row.get("last_status_recorded_at")),
                age_seconds=age or 0,
            )
        )
    return SystemsResponse(
        computed_at=_iso(now),
        staleness_posture=_overall_posture([s.staleness_posture for s in systems]),
        systems=systems,
    )


def compute_queue_response(rows: list[dict[str, Any]], now: datetime) -> QueueResponse:
    counts = {"queued": 0, "leased": 0, "failed": 0, "deferred": 0}
    stale_leases = 0
    active_ages: list[int] = []
    stale_before = now - timedelta(seconds=QUEUE_STALE_LEASE_GRACE_SECONDS)

    for row in rows:
        status = row.get("queue_status")
        bucket = _QUEUE_STATUS_TO_BUCKET.get(status)
        if bucket is not None:
            counts[bucket] += 1

        if status == PS_QUEUE_STATUS_CLAIMED_FOR_SEND:
            expires_at = row.get("claim_lease_expires_at")
            if expires_at is not None and _as_utc(expires_at) < stale_before:
                stale_leases += 1

        if status not in PS_QUEUE_TERMINAL_STATUSES:
            age = _age_seconds(now, row.get("created_at"))
            if age is not None:
                active_ages.append(age)

    return QueueResponse(
        computed_at=_iso(now),
        status_counts=QueueStatusCounts(**counts),
        stale_leases=stale_leases,
        oldest_item_age_seconds=max(active_ages) if active_ages else 0,
        average_queue_dwell_seconds=(int(sum(active_ages) / len(active_ages)) if active_ages else 0),
        degradation_flags=["stale_lease_detected"] if stale_leases else [],
    )


def compute_freshness_response(rows: list[dict[str, Any]], now: datetime) -> FreshnessResponse:
    sources: list[FreshnessSource] = []
    for row in rows:
        age = _age_seconds(now, row.get("last_status_recorded_at"))
        sources.append(
            FreshnessSource(
                source_id=str(row["service_id"]),
                source_name=row.get("service_name") or str(row["service_id"]),
                staleness_posture=_posture_for_age(age),
                age_seconds=age or 0,
                last_updated_at=_iso(row.get("last_status_recorded_at")),
            )
        )
    return FreshnessResponse(
        computed_at=_iso(now),
        overall_staleness_posture=_overall_posture([s.staleness_posture for s in sources]),
        max_source_age_seconds=max((s.age_seconds for s in sources), default=0),
        sources=sources,
    )


def compose_overview_response(
    systems: SystemsResponse,
    queue: QueueResponse,
    freshness: FreshnessResponse,
    now: datetime,
) -> OverviewResponse:
    healthy = sum(1 for s in systems.systems if s.status == SystemStatus.HEALTHY)
    degraded = sum(1 for s in systems.systems if s.status == SystemStatus.DEGRADED)
    offline = sum(1 for s in systems.systems if s.status == SystemStatus.OFFLINE)
    stale_sources = sum(
        1 for s in freshness.sources if s.staleness_posture == StalenessPosture.STALE
    )

    flags = list(queue.degradation_flags)
    if offline:
        flags.append("offline_system_detected")
    if degraded:
        flags.append("degraded_system_detected")
    if stale_sources:
        flags.append("stale_source_detected")

    return OverviewResponse(
        computed_at=_iso(now),
        window_start=_iso(now - timedelta(hours=1)),
        window_end=_iso(now),
        staleness_posture=_overall_posture(
            [systems.staleness_posture, freshness.overall_staleness_posture]
        ),
        degradation_flags=flags,
        systems_summary=SystemsSummary(
            total_systems=len(systems.systems),
            healthy_systems=healthy,
            degraded_systems=degraded,
            offline_systems=offline,
        ),
        queue_summary=QueueSummary(
            status_counts=queue.status_counts,
            stale_leases=queue.stale_leases,
            oldest_item_age_seconds=queue.oldest_item_age_seconds,
            average_queue_dwell_seconds=queue.average_queue_dwell_seconds,
        ),
        freshness_summary=FreshnessSummary(
            sources_total=len(freshness.sources),
            stale_sources=stale_sources,
            max_source_age_seconds=freshness.max_source_age_seconds,
        ),
    )


async def build_systems_response(
    reader: AnalyticsReader, now: datetime | None = None
) -> SystemsResponse:
    now = now or _utcnow()
    return compute_systems_response(await reader.fetch_system_rows(), now)


async def build_queue_response(reader: AnalyticsReader, now: datetime | None = None) -> QueueResponse:
    now = now or _utcnow()
    return compute_queue_response(await reader.fetch_queue_rows(), now)


async def build_freshness_response(
    reader: AnalyticsReader, now: datetime | None = None
) -> FreshnessResponse:
    now = now or _utcnow()
    return compute_freshness_response(await reader.fetch_freshness_rows(), now)


async def build_overview_response(
    reader: AnalyticsReader, now: datetime | None = None
) -> OverviewResponse:
    now = now or _utcnow()
    systems = await build_systems_response(reader, now)
    queue = await build_queue_response(reader, now)
    freshness = await build_freshness_response(reader, now)
    return compose_overview_response(systems, queue, freshness, now)

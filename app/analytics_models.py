"""Typed read-only analytics response models for DF Local Foundation."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

try:  # Pydantic v2
    from pydantic import ConfigDict
except ImportError:  # pragma: no cover
    ConfigDict = None  # type: ignore[assignment]


class AnalyticsBaseModel(BaseModel):
    """Base model with alias support for `_derived`."""

    if ConfigDict is not None:  # pragma: no branch
        model_config = ConfigDict(populate_by_name=True)
    else:  # pragma: no cover

        class Config:
            allow_population_by_field_name = True


class SystemStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


class StalenessPosture(StrEnum):
    FRESH = "fresh"
    AGING = "aging"
    STALE = "stale"
    UNKNOWN = "unknown"


class AnalyticsEnvelope(AnalyticsBaseModel):
    derived: bool = Field(default=True, alias="_derived")
    schema_version: str = "v1"
    computed_at: str


class SystemsSummary(AnalyticsBaseModel):
    total_systems: int
    healthy_systems: int
    degraded_systems: int
    offline_systems: int


class QueueStatusCounts(AnalyticsBaseModel):
    queued: int
    leased: int
    failed: int
    deferred: int


class QueueSummary(AnalyticsBaseModel):
    status_counts: QueueStatusCounts
    stale_leases: int
    oldest_item_age_seconds: int
    average_queue_dwell_seconds: int


class FreshnessSummary(AnalyticsBaseModel):
    sources_total: int
    stale_sources: int
    max_source_age_seconds: int


class OverviewResponse(AnalyticsEnvelope):
    window_start: str
    window_end: str
    staleness_posture: StalenessPosture
    degradation_flags: list[str]
    systems_summary: SystemsSummary
    queue_summary: QueueSummary
    freshness_summary: FreshnessSummary


class SystemEntry(AnalyticsBaseModel):
    system_id: str
    system_name: str
    status: SystemStatus
    staleness_posture: StalenessPosture
    last_success_at: str | None
    age_seconds: int


class SystemsResponse(AnalyticsEnvelope):
    staleness_posture: StalenessPosture
    systems: list[SystemEntry]


class QueueResponse(AnalyticsEnvelope):
    status_counts: QueueStatusCounts
    stale_leases: int
    oldest_item_age_seconds: int
    average_queue_dwell_seconds: int
    degradation_flags: list[str]


class FreshnessSource(AnalyticsBaseModel):
    source_id: str
    source_name: str
    staleness_posture: StalenessPosture
    age_seconds: int
    last_updated_at: str | None


class FreshnessResponse(AnalyticsEnvelope):
    overall_staleness_posture: StalenessPosture
    max_source_age_seconds: int
    sources: list[FreshnessSource]


def model_to_dict(model: AnalyticsBaseModel) -> dict[str, Any]:
    """Return a dict with aliases preserved across Pydantic versions."""
    if hasattr(model, "model_dump"):
        return model.model_dump(by_alias=True)  # type: ignore[attr-defined]
    return model.dict(by_alias=True)  # type: ignore[attr-defined]

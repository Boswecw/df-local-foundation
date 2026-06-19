"""Unit tests for read-only analytics compute functions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.analytics_models import StalenessPosture, SystemStatus
from app.analytics_services import (
    _posture_for_age,
    compute_freshness_response,
    compute_queue_response,
    compute_systems_response,
)

NOW = datetime(2026, 6, 4, 12, 0, 0, tzinfo=UTC)


def test_posture_thresholds_are_fresh_aging_stale() -> None:
    assert _posture_for_age(None) == StalenessPosture.UNKNOWN
    assert _posture_for_age(0) == StalenessPosture.FRESH
    assert _posture_for_age(299) == StalenessPosture.FRESH
    assert _posture_for_age(300) == StalenessPosture.AGING
    assert _posture_for_age(899) == StalenessPosture.AGING
    assert _posture_for_age(900) == StalenessPosture.STALE


def test_queue_buckets_cover_all_lifecycle_states() -> None:
    rows = [
        {"queue_status": status, "created_at": NOW - timedelta(seconds=60), "claim_lease_expires_at": None}
        for status in (
            "staged",
            "queued",
            "claimed_for_send",
            "awaiting_receipt_reconciliation",
            "send_failed_retryable",
            "rejected",
            "dead_lettered",
            "accepted",
        )
    ]
    resp = compute_queue_response(rows, NOW)
    assert resp.status_counts.queued == 2
    assert resp.status_counts.leased == 2
    assert resp.status_counts.failed == 1
    assert resp.status_counts.deferred == 2
    assert resp.average_queue_dwell_seconds == 60
    assert resp.stale_leases == 0
    assert resp.degradation_flags == []


def test_queue_stale_lease_detected_only_when_expired() -> None:
    rows = [
        {
            "queue_status": "claimed_for_send",
            "created_at": NOW - timedelta(seconds=300),
            "claim_lease_expires_at": NOW - timedelta(seconds=1),
        },
        {
            "queue_status": "claimed_for_send",
            "created_at": NOW - timedelta(seconds=10),
            "claim_lease_expires_at": NOW + timedelta(seconds=60),
        },
    ]
    resp = compute_queue_response(rows, NOW)
    assert resp.stale_leases == 1
    assert resp.degradation_flags == ["stale_lease_detected"]
    assert resp.oldest_item_age_seconds == 300


def test_systems_status_mapping_from_service_state() -> None:
    rows = [
        {"service_id": "a", "service_name": "A", "service_state": "ready", "last_status_recorded_at": NOW},
        {"service_id": "b", "service_name": "B", "service_state": "migrating", "last_status_recorded_at": NOW},
        {"service_id": "c", "service_name": "C", "service_state": "unavailable", "last_status_recorded_at": NOW},
        {"service_id": "d", "service_name": "D", "service_state": None, "last_status_recorded_at": None},
    ]
    resp = compute_systems_response(rows, NOW)
    status_by_id = {s.system_id: s.status for s in resp.systems}
    assert status_by_id["a"] == SystemStatus.HEALTHY
    assert status_by_id["b"] == SystemStatus.DEGRADED
    assert status_by_id["c"] == SystemStatus.OFFLINE
    assert status_by_id["d"] == SystemStatus.UNKNOWN


def test_freshness_overall_and_max_age() -> None:
    rows = [
        {"service_id": "a", "service_name": "A", "last_status_recorded_at": NOW - timedelta(seconds=10)},
        {"service_id": "b", "service_name": "B", "last_status_recorded_at": NOW - timedelta(seconds=1000)},
    ]
    resp = compute_freshness_response(rows, NOW)
    assert resp.max_source_age_seconds == 1000
    assert resp.overall_staleness_posture == StalenessPosture.STALE


def test_empty_inputs_are_unknown_and_zero() -> None:
    assert compute_systems_response([], NOW).staleness_posture == StalenessPosture.UNKNOWN
    freshness = compute_freshness_response([], NOW)
    assert freshness.sources == []
    assert freshness.max_source_age_seconds == 0
    assert freshness.overall_staleness_posture == StalenessPosture.UNKNOWN
    queue = compute_queue_response([], NOW)
    assert queue.oldest_item_age_seconds == 0
    assert queue.average_queue_dwell_seconds == 0

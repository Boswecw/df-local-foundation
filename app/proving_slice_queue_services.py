"""Read-only proving-slice queue services for DF Local Foundation."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any, Protocol

logger = logging.getLogger(__name__)

PS_QUEUE_STATUS_STAGED = "staged"
PS_QUEUE_STATUS_QUEUED = "queued"
PS_QUEUE_STATUS_CLAIMED_FOR_SEND = "claimed_for_send"
PS_QUEUE_STATUS_SEND_FAILED_RETRYABLE = "send_failed_retryable"
PS_QUEUE_STATUS_AWAITING_RECEIPT_RECONCILIATION = "awaiting_receipt_reconciliation"
PS_QUEUE_STATUS_ACCEPTED = "accepted"
PS_QUEUE_STATUS_REJECTED = "rejected"
PS_QUEUE_STATUS_DEAD_LETTERED = "dead_lettered"

PS_STALENESS_FRESH = "fresh"
PS_STALENESS_STALE = "stale"
PS_STALENESS_THRESHOLD_SECONDS = 900

_QUEUE_SQL = """
    SELECT s.*, a.payload_json, a.produced_by_system
    FROM runtime_promotion.ps_promotion_staging s
    JOIN runtime_promotion.ps_local_artifacts a
      ON a.artifact_id = s.artifact_id
    WHERE s.queue_status != $1
    ORDER BY s.updated_at DESC
    LIMIT $2
"""

_DETAIL_STAGING_SQL = """
    SELECT *
    FROM runtime_promotion.ps_promotion_staging
    WHERE staged_promotion_id = $1
"""

_DETAIL_ARTIFACT_SQL = """
    SELECT *
    FROM runtime_promotion.ps_local_artifacts
    WHERE artifact_id = $1
"""

_DETAIL_ATTEMPTS_SQL = """
    SELECT *
    FROM runtime_promotion.ps_promotion_attempts
    WHERE staged_promotion_id = $1
    ORDER BY attempt_number ASC
"""

_LIFECYCLE_PLAIN_LANGUAGE = {
    PS_QUEUE_STATUS_STAGED: "Admitted locally and waiting for the next promotion check.",
    PS_QUEUE_STATUS_QUEUED: "Queued for outbound promotion to shared truth.",
    PS_QUEUE_STATUS_CLAIMED_FOR_SEND: "Currently being sent to shared intake.",
    PS_QUEUE_STATUS_SEND_FAILED_RETRYABLE: "Last send attempt failed. Will retry automatically.",
    PS_QUEUE_STATUS_AWAITING_RECEIPT_RECONCILIATION: (
        "Send outcome is uncertain. Awaiting receipt confirmation before marking accepted."
    ),
    PS_QUEUE_STATUS_ACCEPTED: "Accepted by shared intake. Canonical shared truth exists.",
    PS_QUEUE_STATUS_REJECTED: "Rejected by shared intake. See rejection reason below.",
    PS_QUEUE_STATUS_DEAD_LETTERED: (
        "Automatic retries exhausted or non-retryable failure. Operator review required."
    ),
}


class ProvingSliceQueueReadError(RuntimeError):
    """Raised when the support foundation cannot read proving-slice queue rows."""


class ProvingSliceQueueEntryNotFound(RuntimeError):
    """Raised when a requested proving-slice queue entry does not exist."""


class ProvingSliceQueueReader(Protocol):
    async def fetch_queue_rows(self, limit: int) -> list[dict[str, Any]]:
        """Fetch non-accepted queue rows joined to artifact payloads."""

    async def fetch_detail_rows(
        self,
        staged_promotion_id: str,
    ) -> tuple[dict[str, Any] | None, dict[str, Any], list[dict[str, Any]]]:
        """Fetch staging, artifact, and attempt rows for one queue entry."""


class AsyncpgProvingSliceQueueReader:
    """Asyncpg-backed proving-slice queue reader for the support foundation."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    async def fetch_queue_rows(self, limit: int) -> list[dict[str, Any]]:
        import asyncpg

        try:
            conn = await asyncpg.connect(self._dsn)
            try:
                rows = await conn.fetch(
                    _QUEUE_SQL,
                    PS_QUEUE_STATUS_ACCEPTED,
                    max(1, min(limit, 1000)),
                )
                return [dict(row) for row in rows]
            finally:
                await conn.close()
        except Exception as exc:
            logger.warning("df_local.proving_slice_queue_read_failed error=%s", type(exc).__name__)
            raise ProvingSliceQueueReadError("proving_slice_queue_read_failed") from exc

    async def fetch_detail_rows(
        self,
        staged_promotion_id: str,
    ) -> tuple[dict[str, Any] | None, dict[str, Any], list[dict[str, Any]]]:
        import asyncpg

        try:
            conn = await asyncpg.connect(self._dsn)
            try:
                staging_row = await conn.fetchrow(_DETAIL_STAGING_SQL, staged_promotion_id)
                if staging_row is None:
                    return None, {}, []
                artifact_row = await conn.fetchrow(_DETAIL_ARTIFACT_SQL, staging_row["artifact_id"])
                attempt_rows = await conn.fetch(_DETAIL_ATTEMPTS_SQL, staged_promotion_id)
                return (
                    dict(staging_row),
                    dict(artifact_row) if artifact_row is not None else {},
                    [dict(row) for row in attempt_rows],
                )
            finally:
                await conn.close()
        except Exception as exc:
            logger.warning("df_local.proving_slice_detail_read_failed error=%s", type(exc).__name__)
            raise ProvingSliceQueueReadError("proving_slice_detail_read_failed") from exc


def _json_value(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return value


def _datetime_value(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    raise TypeError(f"expected datetime-compatible value, got {type(value).__name__}")


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def _staleness_posture(updated_at: datetime) -> str:
    compared = updated_at.replace(tzinfo=UTC) if updated_at.tzinfo is None else updated_at
    age = datetime.now(UTC) - compared
    return PS_STALENESS_STALE if age.total_seconds() > PS_STALENESS_THRESHOLD_SECONDS else PS_STALENESS_FRESH


def compute_queue_row(staging_row: dict[str, Any], artifact_row: dict[str, Any]) -> dict[str, Any]:
    """Build the source-compatible proving-slice queue row shape."""
    payload = _json_value(artifact_row.get("payload_json"), {})
    updated_at = _datetime_value(staging_row["updated_at"])
    created_at = _datetime_value(staging_row["created_at"])
    return {
        "staged_promotion_id": staging_row["staged_promotion_id"],
        "artifact_id": staging_row["artifact_id"],
        "system_id": payload.get("system_id", artifact_row.get("produced_by_system", "")),
        "issue_summary": payload.get("operator_summary", ""),
        "artifact_family": staging_row["artifact_family"],
        "drift_class": payload.get("drift_class"),
        "promotion_state": staging_row["queue_status"],
        "confidence_posture": payload.get("confidence", "unknown"),
        "created_at": _iso(created_at),
        "last_state_change_at": _iso(updated_at),
        "staleness_posture": _staleness_posture(updated_at),
        "changed_since_last_view": True,
        "attempt_count": staging_row.get("promotion_attempt_count", 0),
    }


def compute_queue_response(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return non-accepted staging rows as source-compatible queue rows."""
    return [
        compute_queue_row(
            row,
            {
                "payload_json": _json_value(row.get("payload_json"), {}),
                "produced_by_system": row.get("produced_by_system", ""),
            },
        )
        for row in rows
    ]


def compute_detail_response(
    staging_row: dict[str, Any] | None,
    artifact_row: dict[str, Any],
    attempt_rows: list[dict[str, Any]],
    staged_promotion_id: str,
) -> dict[str, Any]:
    """Build the source-compatible proving-slice detail shape."""
    if staging_row is None:
        raise ProvingSliceQueueEntryNotFound(staged_promotion_id)

    payload = _json_value(artifact_row.get("payload_json"), {})
    status = staging_row["queue_status"]
    updated_at = _datetime_value(staging_row["updated_at"])
    dead_letter_reason = staging_row.get("dead_letter_reason") or ""

    rejection_dead_letter_block = None
    if status in (PS_QUEUE_STATUS_REJECTED, PS_QUEUE_STATUS_DEAD_LETTERED):
        rejection_dead_letter_block = {
            "state": status,
            "rejection_class": staging_row.get("last_remote_error_class"),
            "dead_letter_reason": staging_row.get("dead_letter_reason"),
            "retry_allowed": (
                status == PS_QUEUE_STATUS_DEAD_LETTERED
                and not dead_letter_reason.startswith("Retry ceiling")
            ),
            "operator_action_required": status == PS_QUEUE_STATUS_DEAD_LETTERED,
            "_derived": True,
        }

    return {
        "staged_promotion_id": staging_row["staged_promotion_id"],
        "artifact_id": staging_row["artifact_id"],
        "summary_header": {
            "issue_title": payload.get("operator_summary", "No summary available"),
            "target_system": payload.get("system_id", artifact_row.get("produced_by_system", "")),
            "confidence_posture": payload.get("confidence", "unknown"),
            "staleness_posture": _staleness_posture(updated_at),
            "promotion_lifecycle_state": status,
            "concise_explanation": _LIFECYCLE_PLAIN_LANGUAGE.get(status, status),
            "_derived": True,
        },
        "evidence_summary": {
            "evidence_refs": payload.get("evidence_refs", []),
            "affected_components": payload.get("affected_components", []),
            "detection_source": payload.get("detection_source"),
            "declared_truth_ref": payload.get("declared_truth_ref"),
            "observed_truth_ref": payload.get("observed_truth_ref"),
        },
        "promotion_lifecycle_block": {
            "state": status,
            "plain_language": _LIFECYCLE_PLAIN_LANGUAGE.get(status, status),
            "attempt_count": staging_row.get("promotion_attempt_count", 0),
            "remote_receipt_ref": staging_row.get("remote_receipt_ref"),
            "last_transport_error": staging_row.get("last_transport_error"),
            "_derived": True,
            "_note": "This block is derived from staging state. Not canonical lifecycle truth.",
        },
        "rejection_dead_letter_block": rejection_dead_letter_block,
        "audit_summary": [
            {
                "attempted_at": str(row.get("attempted_at", "")),
                "attempt_number": row.get("attempt_number"),
                "transport_action": row.get("transport_action"),
                "outcome_class": row.get("outcome_class"),
                "remote_status_code": row.get("remote_status_code"),
            }
            for row in sorted(attempt_rows, key=lambda row: row.get("attempt_number", 0))
        ],
    }


async def build_queue_response(
    reader: ProvingSliceQueueReader,
    limit: int,
) -> list[dict[str, Any]]:
    return compute_queue_response(await reader.fetch_queue_rows(limit))


async def build_detail_response(
    reader: ProvingSliceQueueReader,
    staged_promotion_id: str,
) -> dict[str, Any]:
    staging_row, artifact_row, attempt_rows = await reader.fetch_detail_rows(staged_promotion_id)
    return compute_detail_response(staging_row, artifact_row, attempt_rows, staged_promotion_id)

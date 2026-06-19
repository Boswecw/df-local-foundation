"""Read-only healing-proposal services for DF Local Foundation."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Protocol

logger = logging.getLogger(__name__)

_HEALING_PROPOSAL_SELECT = """
    SELECT proposal_id, source_system, repo_id, commit_sha, severity,
           status, schema_version, envelope_json, decision_json, created_at
    FROM healing_proposals
"""

_HEALING_PROPOSAL_GET_SQL = f"""
{_HEALING_PROPOSAL_SELECT}
    WHERE proposal_id = $1
"""


class HealingProposalReadError(RuntimeError):
    """Raised when the support foundation cannot read healing-proposal rows."""


class HealingProposalNotFound(RuntimeError):
    """Raised when a requested healing proposal does not exist."""


class HealingProposalReader(Protocol):
    async def fetch_healing_proposal_rows(
        self,
        status: str | None,
        repo_id: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Fetch healing proposals with optional source-compatible filters."""

    async def fetch_healing_proposal_row(self, proposal_id: str) -> dict[str, Any] | None:
        """Fetch one healing proposal by id."""


class AsyncpgHealingProposalReader:
    """Asyncpg-backed healing-proposal reader for the support foundation."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    async def fetch_healing_proposal_rows(
        self,
        status: str | None,
        repo_id: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        import asyncpg

        clauses: list[str] = []
        values: list[Any] = []
        if status:
            values.append(status)
            clauses.append(f"status = ${len(values)}")
        if repo_id:
            values.append(repo_id)
            clauses.append(f"repo_id = ${len(values)}")

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        values.append(max(1, min(limit, 200)))
        sql = f"{_HEALING_PROPOSAL_SELECT}{where} ORDER BY created_at DESC LIMIT ${len(values)}"

        try:
            conn = await asyncpg.connect(self._dsn)
            try:
                return [dict(row) for row in await conn.fetch(sql, *values)]
            finally:
                await conn.close()
        except Exception as exc:
            logger.warning("df_local.healing_proposals_read_failed error=%s", type(exc).__name__)
            raise HealingProposalReadError("healing_proposals_read_failed") from exc

    async def fetch_healing_proposal_row(self, proposal_id: str) -> dict[str, Any] | None:
        import asyncpg

        try:
            conn = await asyncpg.connect(self._dsn)
            try:
                row = await conn.fetchrow(_HEALING_PROPOSAL_GET_SQL, proposal_id)
                return dict(row) if row is not None else None
            finally:
                await conn.close()
        except Exception as exc:
            logger.warning("df_local.healing_proposal_read_failed error=%s", type(exc).__name__)
            raise HealingProposalReadError("healing_proposal_read_failed") from exc


def _json_value(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return value


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def _proposal_shape(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "proposal_id": row["proposal_id"],
        "source_system": row["source_system"],
        "repo_id": row.get("repo_id"),
        "commit_sha": row.get("commit_sha"),
        "severity": row["severity"],
        "status": row["status"],
        "schema_version": row["schema_version"],
        "envelope": _json_value(row.get("envelope_json"), {}),
        "decision": _json_value(row.get("decision_json"), None),
        "created_at": _iso(row.get("created_at")),
    }


def compute_healing_proposals_response(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the source-compatible healing-proposals list shape."""
    items = [_proposal_shape(row) for row in rows]
    return {"items": items, "count": len(items)}


def compute_healing_proposal_response(
    row: dict[str, Any] | None,
    proposal_id: str,
) -> dict[str, Any]:
    """Return the source-compatible healing-proposal detail shape."""
    if row is None:
        raise HealingProposalNotFound(proposal_id)
    return _proposal_shape(row)


async def build_healing_proposals_response(
    reader: HealingProposalReader,
    status: str | None,
    repo_id: str | None,
    limit: int,
) -> dict[str, Any]:
    return compute_healing_proposals_response(
        await reader.fetch_healing_proposal_rows(status, repo_id, limit)
    )


async def build_healing_proposal_response(
    reader: HealingProposalReader,
    proposal_id: str,
) -> dict[str, Any]:
    return compute_healing_proposal_response(
        await reader.fetch_healing_proposal_row(proposal_id),
        proposal_id,
    )

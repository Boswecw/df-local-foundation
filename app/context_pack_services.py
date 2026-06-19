"""Read-only context-pack services for DF Local Foundation."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Protocol

logger = logging.getLogger(__name__)

_CONTEXT_PACK_SQL = """
    SELECT context_pack_id, bundle_hash, task_intent_id,
           primary_text, supporting_json, metadata_json, created_at
    FROM context_packs
    WHERE context_pack_id = $1
"""


class ContextPackReadError(RuntimeError):
    """Raised when the support foundation cannot read context-pack rows."""


class ContextPackNotFound(RuntimeError):
    """Raised when a requested context pack does not exist."""


class ContextPackReader(Protocol):
    async def fetch_context_pack_row(self, context_pack_id: str) -> dict[str, Any] | None:
        """Fetch one context-pack row."""


class AsyncpgContextPackReader:
    """Asyncpg-backed context-pack reader for the support foundation."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    async def fetch_context_pack_row(self, context_pack_id: str) -> dict[str, Any] | None:
        import asyncpg

        try:
            conn = await asyncpg.connect(self._dsn)
            try:
                row = await conn.fetchrow(_CONTEXT_PACK_SQL, context_pack_id)
                return dict(row) if row is not None else None
            finally:
                await conn.close()
        except Exception as exc:
            logger.warning("df_local.context_pack_read_failed error=%s", type(exc).__name__)
            raise ContextPackReadError("context_pack_read_failed") from exc


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


def compute_context_pack_response(row: dict[str, Any] | None, context_pack_id: str) -> dict[str, Any]:
    """Return the NeuroForge-compatible context-pack read shape."""
    if row is None:
        raise ContextPackNotFound(context_pack_id)

    metadata = _json_value(row.get("metadata_json"), {})
    supporting = _json_value(row.get("supporting_json"), [])
    metadata = {
        **metadata,
        "context_pack_id": row["context_pack_id"],
        "context_bundle_id": row["context_pack_id"],
        "context_bundle_hash": row["bundle_hash"],
        "task_intent_id": row.get("task_intent_id"),
        "served_from": "precomputed_pact_packet",
    }
    return {
        "primary": row.get("primary_text") or "",
        "supporting": supporting,
        "metadata": metadata,
        "context_pack_id": row["context_pack_id"],
        "bundle_hash": row["bundle_hash"],
        "created_at": _iso(row.get("created_at")),
    }


async def build_context_pack_response(
    reader: ContextPackReader,
    context_pack_id: str,
) -> dict[str, Any]:
    return compute_context_pack_response(
        await reader.fetch_context_pack_row(context_pack_id),
        context_pack_id,
    )

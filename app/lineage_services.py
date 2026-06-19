"""Read-only lineage services for DF Local Foundation."""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)

_LINEAGE_NODE_LIST_SELECT = """
    SELECT node_json
    FROM lineage_nodes
"""

_LINEAGE_NODE_GET_SQL = """
    SELECT node_json
    FROM lineage_nodes
    WHERE node_id = $1
"""

_LINEAGE_DOWNSTREAM_EDGES_SQL = """
    SELECT edge_json, target_node_id
    FROM lineage_edges
    WHERE source_node_id = $1
    ORDER BY created_at
"""

_LINEAGE_NODES_BY_IDS_SQL = """
    SELECT node_json
    FROM lineage_nodes
    WHERE node_id = ANY($1::text[])
"""


class LineageReadError(RuntimeError):
    """Raised when the support foundation cannot read lineage rows."""


class LineageNodeNotFound(RuntimeError):
    """Raised when a requested lineage node does not exist."""


class LineageReader(Protocol):
    async def fetch_lineage_node_rows(
        self,
        node_type: str | None,
        source_system: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Fetch lineage node rows with optional source-compatible filters."""

    async def fetch_lineage_node_row(self, node_id: str) -> dict[str, Any] | None:
        """Fetch one lineage node row."""

    async def fetch_downstream_edge_rows(self, node_id: str) -> list[dict[str, Any]]:
        """Fetch downstream edge rows for a source node."""

    async def fetch_lineage_nodes_by_ids(self, node_ids: list[str]) -> list[dict[str, Any]]:
        """Fetch lineage node rows by ids."""


class AsyncpgLineageReader:
    """Asyncpg-backed lineage reader for the support foundation."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    async def fetch_lineage_node_rows(
        self,
        node_type: str | None,
        source_system: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        import asyncpg

        clauses: list[str] = []
        values: list[Any] = []
        if node_type:
            values.append(node_type)
            clauses.append(f"node_type = ${len(values)}")
        if source_system:
            values.append(source_system)
            clauses.append(f"source_system = ${len(values)}")

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        values.append(max(1, min(limit, 1000)))
        sql = f"{_LINEAGE_NODE_LIST_SELECT}{where} ORDER BY created_at DESC LIMIT ${len(values)}"

        try:
            conn = await asyncpg.connect(self._dsn)
            try:
                return [dict(row) for row in await conn.fetch(sql, *values)]
            finally:
                await conn.close()
        except Exception as exc:
            logger.warning("df_local.lineage_nodes_read_failed error=%s", type(exc).__name__)
            raise LineageReadError("lineage_nodes_read_failed") from exc

    async def fetch_lineage_node_row(self, node_id: str) -> dict[str, Any] | None:
        import asyncpg

        try:
            conn = await asyncpg.connect(self._dsn)
            try:
                row = await conn.fetchrow(_LINEAGE_NODE_GET_SQL, node_id)
                return dict(row) if row is not None else None
            finally:
                await conn.close()
        except Exception as exc:
            logger.warning("df_local.lineage_node_read_failed error=%s", type(exc).__name__)
            raise LineageReadError("lineage_node_read_failed") from exc

    async def fetch_downstream_edge_rows(self, node_id: str) -> list[dict[str, Any]]:
        import asyncpg

        try:
            conn = await asyncpg.connect(self._dsn)
            try:
                return [dict(row) for row in await conn.fetch(_LINEAGE_DOWNSTREAM_EDGES_SQL, node_id)]
            finally:
                await conn.close()
        except Exception as exc:
            logger.warning("df_local.lineage_downstream_read_failed error=%s", type(exc).__name__)
            raise LineageReadError("lineage_downstream_read_failed") from exc

    async def fetch_lineage_nodes_by_ids(self, node_ids: list[str]) -> list[dict[str, Any]]:
        if not node_ids:
            return []

        import asyncpg

        try:
            conn = await asyncpg.connect(self._dsn)
            try:
                return [dict(row) for row in await conn.fetch(_LINEAGE_NODES_BY_IDS_SQL, node_ids)]
            finally:
                await conn.close()
        except Exception as exc:
            logger.warning("df_local.lineage_target_nodes_read_failed error=%s", type(exc).__name__)
            raise LineageReadError("lineage_target_nodes_read_failed") from exc


def _json_value(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return value


def compute_lineage_nodes_response(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the source-compatible lineage node list shape."""
    return {"nodes": [_json_value(row.get("node_json"), {}) for row in rows]}


def compute_lineage_node_response(row: dict[str, Any] | None, node_id: str) -> dict[str, Any]:
    """Return the source-compatible lineage node detail shape."""
    if row is None:
        raise LineageNodeNotFound(node_id)
    return _json_value(row.get("node_json"), {})


def compute_lineage_downstream_response(
    node_id: str,
    edge_rows: list[dict[str, Any]],
    node_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return the source-compatible downstream lineage shape."""
    return {
        "source_node_id": node_id,
        "edges": [_json_value(row.get("edge_json"), {}) for row in edge_rows],
        "nodes": [_json_value(row.get("node_json"), {}) for row in node_rows],
    }


async def build_lineage_nodes_response(
    reader: LineageReader,
    node_type: str | None,
    source_system: str | None,
    limit: int,
) -> dict[str, Any]:
    return compute_lineage_nodes_response(
        await reader.fetch_lineage_node_rows(node_type, source_system, limit)
    )


async def build_lineage_node_response(reader: LineageReader, node_id: str) -> dict[str, Any]:
    return compute_lineage_node_response(await reader.fetch_lineage_node_row(node_id), node_id)


async def build_lineage_downstream_response(
    reader: LineageReader,
    node_id: str,
) -> dict[str, Any]:
    edge_rows = await reader.fetch_downstream_edge_rows(node_id)
    target_ids = [str(row["target_node_id"]) for row in edge_rows]
    node_rows = await reader.fetch_lineage_nodes_by_ids(target_ids)
    return compute_lineage_downstream_response(node_id, edge_rows, node_rows)

"""Integration tests: AuthorForge NIL v2 schema invariants + rebuild equivalence.

Proves the DF Local Foundation producer obligation from the NIL v2
support-service delegation amendment:

  * the authority CHECK constraints reject prohibited rows at the data boundary
    (the no-authority-auto-commit gate), and
  * current-state (nil_canon_current) is rebuildable from the append-only log
    (rebuild equivalence), including supersession.

Integration-level: requires a real PostgreSQL. Skipped unless ``NIL_TEST_DSN``
is set, e.g.::

    NIL_TEST_DSN=postgresql://postgres@/nilcheck?host=/tmp/nilpg \
        pytest tests/nil/ -m integration

The test owns its scratch state: it stubs ``core_schema_versions`` if absent,
applies ``sql/apps/authorforge/0003_authorforge_nil_schema.sql`` (idempotent),
and operates only in the ``authorforge.*`` namespace.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

SCHEMA_SQL = (
    Path(__file__).resolve().parents[2]
    / "sql"
    / "apps"
    / "authorforge"
    / "0003_authorforge_nil_schema.sql"
)


def _dsn() -> str:
    dsn = os.environ.get("NIL_TEST_DSN")
    if not dsn:
        pytest.skip("NIL schema integration test requires NIL_TEST_DSN")
    return dsn


async def _connect():
    import asyncpg

    conn = await asyncpg.connect(_dsn())
    # The 0003 SQL updates the foundation's per-app version row; stub it if the
    # scratch database does not already carry the core table.
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS core_schema_versions(
            target text PRIMARY KEY, current_version text,
            expected_version text, status text, updated_at timestamptz);
        INSERT INTO core_schema_versions(target) VALUES('authorforge')
            ON CONFLICT (target) DO NOTHING;
        """
    )
    await conn.execute(SCHEMA_SQL.read_text())
    return conn


def _tx_sql(**over: object) -> tuple[str, list]:
    row = {
        "workspace_id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "project_mode": "fiction",
        "writer_authority_mode": "strict_writer_approval",
        "domain": "canon",
        "transaction_type": "canon_fact",
        "status": "accepted",
        "detection_class": "deterministic",
        "authority_class": "accepted_authority",
        "approval_tier": "B_review",
        "confidence": None,
        "provider_receipt_id": None,
        "schema_version": 1,
        "payload": '{"text":"x"}',
        "block_id": uuid.uuid4(),
    }
    row.update(over)
    cols = list(row)
    placeholders = ", ".join(f"${i + 1}" for i in range(len(cols)))
    sql = (
        f"INSERT INTO authorforge.nil_transactions ({', '.join(cols)}, committed_at) "
        f"VALUES ({placeholders}, now()) RETURNING transaction_id"
    )
    return sql, [row[c] for c in cols]


@pytest.mark.asyncio
async def test_check_constraints_reject_prohibited_rows() -> None:
    import asyncpg

    conn = await _connect()
    try:
        # valid accepted canon tx is allowed
        sql, args = _tx_sql()
        assert await conn.fetchval(sql, *args) is not None

        # manuscript_text may never be Tier A
        with pytest.raises(asyncpg.CheckViolationError):
            sql, args = _tx_sql(
                authority_class="manuscript_text",
                approval_tier="A_auto",
                writer_authority_mode="experimental_low_risk_auto",
            )
            await conn.execute(sql, *args)

        # non-metadata Tier A requires experimental mode
        with pytest.raises(asyncpg.CheckViolationError):
            sql, args = _tx_sql(
                authority_class="candidate_authority",
                approval_tier="A_auto",
                writer_authority_mode="assisted_metadata_auto",
            )
            await conn.execute(sql, *args)

        # heuristic transactions require a confidence score
        with pytest.raises(asyncpg.CheckViolationError):
            sql, args = _tx_sql(detection_class="heuristic", provider_receipt_id="r1")
            await conn.execute(sql, *args)

        # heuristic authority-bearing extraction requires a provider receipt
        with pytest.raises(asyncpg.CheckViolationError):
            sql, args = _tx_sql(
                detection_class="heuristic",
                authority_class="candidate_authority",
                confidence=0.7,
            )
            await conn.execute(sql, *args)
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_rebuild_equivalence_and_supersession() -> None:
    conn = await _connect()
    try:
        block = uuid.uuid4()
        ws, proj = uuid.uuid4(), uuid.uuid4()

        sql, args = _tx_sql(
            workspace_id=ws, project_id=proj, block_id=block,
            payload='{"text":"iron key"}',
        )
        original_tx = await conn.fetchval(sql, *args)

        await conn.execute("SELECT authorforge.nil_rebuild_canon_current()")
        row = await conn.fetchrow(
            "SELECT text FROM authorforge.nil_canon_current WHERE block_id=$1", block
        )
        assert row is not None and row["text"] == "iron key"

        # a superseding accepted tx becomes the current row after rebuild
        sql, args = _tx_sql(
            workspace_id=ws, project_id=proj, block_id=block,
            payload='{"text":"brass key"}', supersedes_id=original_tx,
        )
        await conn.execute(sql, *args)
        await conn.execute("SELECT authorforge.nil_rebuild_canon_current()")

        rows = await conn.fetch(
            "SELECT text FROM authorforge.nil_canon_current WHERE block_id=$1", block
        )
        assert len(rows) == 1
        assert rows[0]["text"] == "brass key"
    finally:
        await conn.close()

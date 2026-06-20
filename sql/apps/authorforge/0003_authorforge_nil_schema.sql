-- AuthorForge — NIL (Narrative Intelligence Layer) v2 schema
-- Version: 0003
-- Date: 2026-06-20
--
-- Run by AuthorForge against DF Local Foundation (not by the foundation itself).
-- Implements the DF Local Foundation producer obligation from the NIL v2
-- support-service delegation amendment: the append-only transaction log, the
-- current-state cache, and the review/approval queues that the CQRS-lite core
-- commits through. AuthorForge orchestrates; DF Local owns this local authority
-- (edge operational memory), per the ecosystem boundary.
--
-- Source plan: NIL_v2_Writer_Authority_Mode_Plan_Set (files 01, 02, 05, 07).
--
-- Invariants enforced HERE (defense in depth — the same rules FA Local enforces
-- at admission are also enforced at the data boundary, so no path can write a
-- prohibited row):
--   1. The log is authority for history; current-state traces to a source tx.
--   2. manuscript_text may NEVER be Tier A (auto-commit).
--   3. non-metadata Tier A requires experimental_low_risk_auto mode.
--   4. heuristic transactions require a confidence score.
--   5. a heuristic authority-bearing extraction requires a provider receipt.
-- Current-state is derived and rebuildable from the log
-- (authorforge.nil_rebuild_canon_current); rebuild equivalence is a Slice-1 gate.

BEGIN;

CREATE SCHEMA IF NOT EXISTS authorforge;

-- ── Append-only transaction log — authority for history ──────────────────────
-- Ported from NIL v2 file 07 (PostgreSQL shape) into the authorforge.* namespace.

CREATE TABLE IF NOT EXISTS authorforge.nil_transactions (
  transaction_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id          UUID NOT NULL,
  project_id            UUID NOT NULL,
  actor_id              UUID,
  project_mode          TEXT NOT NULL
                          CHECK (project_mode IN ('fiction', 'nonfiction', 'hybrid')),
  writer_authority_mode TEXT NOT NULL
                          CHECK (writer_authority_mode IN (
                            'strict_writer_approval',
                            'assisted_metadata_auto',
                            'experimental_low_risk_auto')),
  domain                TEXT NOT NULL,
  transaction_type      TEXT NOT NULL,
  status                TEXT NOT NULL
                          CHECK (status IN (
                            'proposed', 'accepted', 'rejected',
                            'superseded', 'queued')),
  truth_lane            TEXT,
  claim_kind            TEXT,
  detection_class       TEXT NOT NULL
                          CHECK (detection_class IN ('deterministic', 'heuristic')),
  authority_class       TEXT NOT NULL
                          CHECK (authority_class IN (
                            'derived_metadata',
                            'candidate_authority',
                            'accepted_authority',
                            'manuscript_text')),
  approval_tier         TEXT NOT NULL
                          CHECK (approval_tier IN ('A_auto', 'B_review', 'C_block')),
  confidence            NUMERIC CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  provider_receipt_id   TEXT,
  service_receipt_id    TEXT,
  chapter_id            UUID,
  scene_id              UUID,
  section_id            UUID,
  block_id              UUID,
  schema_version        INT NOT NULL CHECK (schema_version > 0),
  payload               JSONB NOT NULL,
  evidence              JSONB NOT NULL DEFAULT '[]'::jsonb,
  supersedes_id         UUID REFERENCES authorforge.nil_transactions(transaction_id),
  transaction_batch_id  UUID,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  committed_at          TIMESTAMPTZ,

  -- Invariant 2: manuscript_text is never auto-committed.
  CONSTRAINT nil_tx_manuscript_never_tier_a
    CHECK (NOT (approval_tier = 'A_auto' AND authority_class = 'manuscript_text')),

  -- Invariant 3: only derived_metadata may be Tier A unless experimental mode.
  CONSTRAINT nil_tx_non_metadata_tier_a_requires_experimental
    CHECK (NOT (
      approval_tier = 'A_auto'
      AND authority_class <> 'derived_metadata'
      AND writer_authority_mode <> 'experimental_low_risk_auto')),

  -- Invariant 4: heuristic transactions carry a confidence score.
  CONSTRAINT nil_tx_heuristic_requires_confidence
    CHECK (detection_class <> 'heuristic' OR confidence IS NOT NULL),

  -- Invariant 5: heuristic authority-bearing extraction carries a provider receipt.
  CONSTRAINT nil_tx_heuristic_authority_requires_receipt
    CHECK (
      detection_class <> 'heuristic'
      OR authority_class = 'derived_metadata'
      OR provider_receipt_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS nil_transactions_scope_idx
  ON authorforge.nil_transactions (workspace_id, project_id, domain, created_at);
CREATE INDEX IF NOT EXISTS nil_transactions_supersedes_idx
  ON authorforge.nil_transactions (supersedes_id);

-- ── Current-state cache — authority for "now", derived from the log ──────────
-- Slice 1 ships the canon current-state table. Every row traces to a source tx.

CREATE TABLE IF NOT EXISTS authorforge.nil_canon_current (
  node_id       UUID PRIMARY KEY,
  workspace_id  UUID NOT NULL,
  project_id    UUID NOT NULL,
  project_mode  TEXT NOT NULL,
  lane          TEXT NOT NULL,
  text          TEXT NOT NULL,
  confidence    TEXT NOT NULL,
  source_tx_id  UUID NOT NULL REFERENCES authorforge.nil_transactions(transaction_id),
  accepted_by   UUID,
  accepted_at   TIMESTAMPTZ,
  chapter_id    UUID,
  scene_id      UUID,
  section_id    UUID,
  block_id      UUID,
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS nil_canon_current_scope_idx
  ON authorforge.nil_canon_current (workspace_id, project_id);

-- ── Queues — a queued item is not lost, but is not accepted state ────────────
-- Tier B review, Tier C approval, anchor repair, degraded extraction, cloud retry.

CREATE TABLE IF NOT EXISTS authorforge.nil_queue_items (
  queue_item_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  queue          TEXT NOT NULL
                   CHECK (queue IN (
                     'tier_b_review',
                     'tier_c_approval',
                     'anchor_repair',
                     'degraded_extraction',
                     'cloud_retry')),
  workspace_id   UUID NOT NULL,
  project_id     UUID NOT NULL,
  source_tx_id   UUID NOT NULL REFERENCES authorforge.nil_transactions(transaction_id),
  state          TEXT NOT NULL DEFAULT 'open'
                   CHECK (state IN ('open', 'resolved', 'dismissed')),
  detail         JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS nil_queue_items_open_idx
  ON authorforge.nil_queue_items (workspace_id, project_id, queue, state);

-- ── Rebuild equivalence — current-state is derived from the log ──────────────
-- Recompute the canon current-state from the append-only log. For each canon
-- node the authoritative row is the most recent ACCEPTED, non-superseded
-- transaction. Replaying the log must reproduce nil_canon_current exactly
-- (Slice-1 release gate). Idempotent and side-effect-bounded to the canon domain.

CREATE OR REPLACE FUNCTION authorforge.nil_rebuild_canon_current()
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
  DELETE FROM authorforge.nil_canon_current;

  INSERT INTO authorforge.nil_canon_current (
    node_id, workspace_id, project_id, project_mode, lane, text, confidence,
    source_tx_id, accepted_by, accepted_at, chapter_id, scene_id, section_id,
    block_id, updated_at)
  SELECT DISTINCT ON (t.block_id)
    t.block_id,
    t.workspace_id,
    t.project_id,
    t.project_mode,
    COALESCE(t.truth_lane, 'canon'),
    COALESCE(t.payload->>'text', ''),
    COALESCE(t.confidence::text, 'accepted'),
    t.transaction_id,
    t.actor_id,
    t.committed_at,
    t.chapter_id,
    t.scene_id,
    t.section_id,
    t.block_id,
    now()
  FROM authorforge.nil_transactions t
  WHERE t.domain = 'canon'
    AND t.status = 'accepted'
    AND t.block_id IS NOT NULL
    AND NOT EXISTS (
      SELECT 1 FROM authorforge.nil_transactions s
      WHERE s.supersedes_id = t.transaction_id)
  ORDER BY t.block_id, t.created_at DESC;
END;
$$;

-- ── Record the app schema version (foundation tracks the app's own row) ──────

UPDATE core_schema_versions
   SET current_version = '0003',
       expected_version = '0003',
       status = 'current',
       updated_at = NOW()
 WHERE target = 'authorforge';

COMMIT;

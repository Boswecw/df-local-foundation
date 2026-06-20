-- AuthorForge — NIL v2 schema: relax external id columns UUID -> TEXT
-- Version: 0004
-- Date: 2026-06-20
--
-- Run by AuthorForge against DF Local Foundation (not by the foundation itself).
--
-- The 0003 NIL schema modelled workspace_id / project_id / block_id (and the
-- other anchor + actor ids) as UUID, inherited from the generic ecosystem plan.
-- AuthorForge's actual identifiers are NOT UUIDs: workspace_id is the slug
-- 'authorforge.default', project_id is an integer-derived string ('3'), and
-- block ids are TipTap node ids. AuthorForge orchestrates the NIL chain and owns
-- these identifiers, so the durable store adopts AuthorForge's native id shape.
--
-- This relaxes ONLY the external/anchor/actor id columns to TEXT. The internal
-- surrogate keys stay UUID (transaction_id, queue_item_id PKs; source_tx_id and
-- supersedes_id which reference transaction_id). The append-only log, current-
-- state derivation, queues, and all invariant CHECK constraints are unchanged —
-- only the storage type of the id columns changes.
--
-- Idempotent: the foundation bootstrap re-applies every bundled migration on each
-- boot (no version tracking), so this only alters columns still typed `uuid`.

BEGIN;

DO $$
DECLARE
  col record;
BEGIN
  FOR col IN
    SELECT table_name, column_name
      FROM information_schema.columns
     WHERE table_schema = 'authorforge'
       AND table_name IN ('nil_transactions', 'nil_canon_current', 'nil_queue_items')
       AND column_name IN (
             'workspace_id', 'project_id', 'actor_id', 'accepted_by',
             'node_id', 'chapter_id', 'scene_id', 'section_id', 'block_id')
       AND data_type = 'uuid'
  LOOP
    EXECUTE format(
      'ALTER TABLE authorforge.%I ALTER COLUMN %I TYPE TEXT USING %I::text',
      col.table_name, col.column_name, col.column_name);
  END LOOP;
END $$;

UPDATE core_schema_versions
   SET current_version = '0004',
       expected_version = '0004',
       status = 'current',
       updated_at = NOW()
 WHERE target = 'authorforge';

COMMIT;

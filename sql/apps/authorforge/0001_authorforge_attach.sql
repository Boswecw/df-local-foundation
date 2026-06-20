-- AuthorForge — DF Local Foundation Attachment
-- Version: 0001
-- Date: 2026-03-15
--
-- This file is run by AuthorForge on its first startup, not by the foundation.
-- It registers the app and creates its private schema namespace.
--
-- Invariants this migration proves:
-- 1. AuthorForge uses its own namespace (authorforge.*) — never core.*
-- 2. Foundation core tables are not touched here (only inserted into)
-- 3. authorforge.* here holds AuthorForge's EXTERNAL-FACING / SUPPORT data only
--    (projections, public intake, entitlements cache, operational tables —
--    created in 0002). The author's PRIVATE writing (manuscripts, chapters,
--    scenes, lore, canon) lives in AuthorForge's embedded user-data database and
--    never comes here.
-- 4. ForgeCommand can read health state without accessing any authorforge.* tables
--
-- After this migration, authorforge.* is the exclusive namespace of AuthorForge.
-- Foundation does not own, query, or inspect authorforge.* tables.

BEGIN;

-- -------------------------------------------------------
-- Create the AuthorForge private schema namespace.
-- Foundation has no visibility into this schema.
-- -------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS authorforge;

COMMENT ON SCHEMA authorforge IS
    'AuthorForge application schema. Owned exclusively by AuthorForge. '
    'DF Local Foundation does not inspect, query, or own any tables here. '
    'ForgeCommand consumes only the declared health surface — not these tables.';

-- -------------------------------------------------------
-- Register AuthorForge in core_app_registry.
-- This is the ONLY write AuthorForge makes to core.*.
-- -------------------------------------------------------
INSERT INTO core_app_registry
    (app_id, app_version, foundation_version_required, schema_namespace, app_mode)
VALUES
    ('authorforge', '1.0.0', '1.1.0', 'authorforge', 'local')
ON CONFLICT (app_id) DO UPDATE SET
    app_version                 = EXCLUDED.app_version,
    foundation_version_required = EXCLUDED.foundation_version_required,
    app_mode                    = EXCLUDED.app_mode,
    updated_at                  = NOW();

-- -------------------------------------------------------
-- Record AuthorForge's migration version in core_schema_versions.
-- AuthorForge manages this row. Foundation manages the 'core' row.
-- No other app may update this row.
-- -------------------------------------------------------
INSERT INTO core_schema_versions
    (target, schema_namespace, current_version, expected_version, status)
VALUES
    ('authorforge', 'authorforge', '0001', '0001', 'current')
ON CONFLICT (target) DO UPDATE SET
    current_version = EXCLUDED.current_version,
    expected_version = EXCLUDED.expected_version,
    status           = EXCLUDED.status,
    updated_at       = NOW();

-- -------------------------------------------------------
-- Log the attachment event to core_health_events.
-- Coarse telemetry only — no domain content.
-- -------------------------------------------------------
INSERT INTO core_health_events
    (app_id, previous_status, new_status, error_class)
VALUES
    ('authorforge', NULL, 'ready', NULL);

COMMIT;

-- -------------------------------------------------------
-- Post-attachment note:
-- AuthorForge's SUPPORT tables (the external-facing surface) are created in
-- 0002_authorforge_support_schema.sql under the authorforge.* namespace and are
-- managed from the AuthorForge repo. This file only proves the attachment shape.
--
-- What lives in authorforge.* here (created in 0002):
--   CREATE TABLE authorforge.public_content_projection ( ... );
--   CREATE TABLE authorforge.public_support_ticket ( ... );
--   CREATE TABLE authorforge.entitlements ( ... );
--   etc.
--
-- The author's PRIVATE writing (manuscripts, chapters, scenes, lore, canon) does
-- NOT live here — it stays in AuthorForge's embedded user-data database.
-- Foundation has no knowledge of or interest in any authorforge.* table schema.
-- -------------------------------------------------------

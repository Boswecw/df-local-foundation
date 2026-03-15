-- DF Local Foundation — Core Migration 0002
-- Adds backup and export audit log tables.
-- Version: 0002
-- Date: 2026-03-15

BEGIN;

-- -------------------------------------------------------
-- core_backup_log
-- Audit log of all backup operations.
-- Stores metadata only — no backup content.
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS core_backup_log (
    id                  BIGSERIAL   PRIMARY KEY,
    app_id              TEXT        NOT NULL,       -- App that was backed up, or 'core' for foundation-only
    foundation_version  TEXT        NOT NULL,
    schema_version      TEXT        NOT NULL,
    backup_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    format_version      TEXT        NOT NULL DEFAULT '1',
    output_path         TEXT        NOT NULL,       -- Filesystem path of the backup file
    integrity_hash      TEXT        NOT NULL,       -- sha256:... of the backup payload
    includes_namespaces TEXT[]      NOT NULL,       -- e.g. ['core', 'authorforge']
    status              TEXT        NOT NULL
                        CHECK (status IN ('completed', 'failed')),
    error_class         TEXT
                        CHECK (error_class IS NULL OR error_class IN (
                            'integrity_failure',
                            'connection_failure',
                            'startup_failure'
                        ))
);

COMMENT ON TABLE core_backup_log IS
    'Append-only audit log of backup operations. '
    'Stores metadata and integrity hashes — no backup content. '
    'Operator is responsible for retention of backup files.';

-- -------------------------------------------------------
-- core_export_log
-- Audit log of all export operations.
-- Stores metadata only — no export content.
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS core_export_log (
    id                  BIGSERIAL   PRIMARY KEY,
    app_id              TEXT        NOT NULL,
    foundation_version  TEXT        NOT NULL,
    schema_version      TEXT        NOT NULL,
    export_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    format_version      TEXT        NOT NULL DEFAULT '1',
    output_path         TEXT        NOT NULL,       -- Filesystem path of the export file
    namespace           TEXT        NOT NULL,       -- Which schema namespace was exported
    integrity_hash      TEXT        NOT NULL,       -- sha256:... of the export payload
    status              TEXT        NOT NULL
                        CHECK (status IN ('completed', 'failed')),
    error_class         TEXT
                        CHECK (error_class IS NULL OR error_class IN (
                            'integrity_failure',
                            'connection_failure',
                            'startup_failure'
                        ))
);

COMMENT ON TABLE core_export_log IS
    'Append-only audit log of export operations. '
    'Stores metadata and integrity hashes — no export content.';

-- -------------------------------------------------------
-- Update core_schema_versions to reflect 0002
-- -------------------------------------------------------
UPDATE core_schema_versions SET
    current_version = '0002',
    expected_version = '0002',
    status = 'current',
    updated_at = NOW()
WHERE target = 'core';

COMMIT;

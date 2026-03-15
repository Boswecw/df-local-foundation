-- DF Local Foundation — Core Migration 0001
-- Creates the minimal shared metadata tables.
-- Only cross-app discipline lives here. No business schemas.
-- Version: 0001
-- Date: 2026-03-15

BEGIN;

-- -------------------------------------------------------
-- core_schema_versions
-- Tracks applied migration versions per app and core.
-- Each app updates its own row. Foundation updates 'core'.
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS core_schema_versions (
    target              TEXT        NOT NULL,       -- 'core' or app_id
    schema_namespace    TEXT        NOT NULL,       -- PostgreSQL schema name
    current_version     TEXT        NOT NULL,       -- Last applied migration identifier
    expected_version    TEXT        NOT NULL,       -- Declared expected version
    status              TEXT        NOT NULL        -- 'current' | 'pending' | 'failed' | 'unknown'
                        CHECK (status IN ('current', 'pending', 'failed', 'unknown')),
    last_error_class    TEXT                        -- NULL or error class from vocabulary
                        CHECK (last_error_class IS NULL OR last_error_class IN (
                            'migration_failure',
                            'connection_failure',
                            'integrity_failure',
                            'compatibility_failure'
                        )),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (target)
);

COMMENT ON TABLE core_schema_versions IS
    'Migration version tracking for foundation core and all registered apps. '
    'Apps write their own row. Foundation writes the core row. '
    'No app may write another app''s row.';

-- -------------------------------------------------------
-- core_app_registry
-- Registered apps and their compatibility declarations.
-- Malformed or incompatible registrations are rejected.
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS core_app_registry (
    app_id                      TEXT        NOT NULL,   -- Stable lowercase identifier
    app_version                 TEXT        NOT NULL,   -- Semver
    foundation_version_required TEXT        NOT NULL,   -- Minimum foundation version
    schema_namespace            TEXT        NOT NULL,   -- PostgreSQL schema name owned by this app
    app_mode                    TEXT        NOT NULL    -- 'local' | 'hybrid' | 'cloud-enabled'
                                CHECK (app_mode IN ('local', 'hybrid', 'cloud-enabled')),
    registered_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (app_id),

    -- Namespace uniqueness: two apps cannot share a schema namespace
    UNIQUE (schema_namespace),

    -- Reserved namespace guard: apps must not claim 'core'
    CHECK (schema_namespace <> 'core')
);

COMMENT ON TABLE core_app_registry IS
    'Registered Forge apps and their compatibility declarations. '
    'Each app owns exactly one schema_namespace. '
    'The core namespace is reserved and may not be registered.';

-- -------------------------------------------------------
-- core_health_events
-- Coarse lifecycle transition log.
-- Stores status transitions only — no customer data.
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS core_health_events (
    id              BIGSERIAL   PRIMARY KEY,
    app_id          TEXT        NOT NULL,           -- 'core' or app_id
    previous_status TEXT,                           -- NULL if this is the first event
    new_status      TEXT        NOT NULL
                    CHECK (new_status IN ('ready', 'degraded', 'unavailable', 'migrating')),
    error_class     TEXT                            -- NULL or error class from vocabulary
                    CHECK (error_class IS NULL OR error_class IN (
                        'migration_failure',
                        'connection_failure',
                        'integrity_failure',
                        'compatibility_failure',
                        'startup_failure',
                        'restore_blocked'
                    )),
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE core_health_events IS
    'Append-only log of coarse health status transitions. '
    'No customer data, no table contents, no domain metadata. '
    'Only status transitions and error classes.';

-- -------------------------------------------------------
-- Record this migration in core_schema_versions
-- -------------------------------------------------------
INSERT INTO core_schema_versions
    (target, schema_namespace, current_version, expected_version, status)
VALUES
    ('core', 'core', '0001', '0001', 'current')
ON CONFLICT (target) DO UPDATE SET
    current_version = EXCLUDED.current_version,
    expected_version = EXCLUDED.expected_version,
    status = EXCLUDED.status,
    updated_at = NOW();

COMMIT;

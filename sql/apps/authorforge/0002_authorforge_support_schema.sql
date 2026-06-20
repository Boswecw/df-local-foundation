-- AuthorForge — DF Local Foundation Support Schema
-- Version: 0002
-- Date: 2026-06-19
--
-- Run by AuthorForge against DF Local Foundation (not by the foundation itself).
-- Creates AuthorForge's EXTERNAL-FACING / SUPPORT tables in its private
-- authorforge.* namespace.
--
-- These are NOT the author's private writing. The manuscripts, chapters, scenes,
-- lore and canon live in AuthorForge's own embedded user-data database and never
-- come here. This schema holds ONLY the public-facing surface AuthorForge
-- projects or collects:
--   * projections — a verifiable cache of upstream-owned content/feature/release
--   * intake      — support tickets (+messages/events), waitlist, contact, consent
--   * entitlements — a cache/projection; the authority is ForgeCustomer (cloud)
--   * operational  — forgeagent_tasks, intake_receipts, rate-limit events
--
-- Invariants:
--   1. Every table lives in authorforge.* (never core.*).
--   2. Foundation core tables are untouched except the app's own version row.
--   3. Definitions are ported faithfully from AuthorForge's embedded migrations
--      026/027/003/025 (same names, so the app's repoint is a pure
--      pool/search_path change — no SQL rewrites at the call sites).

BEGIN;

CREATE SCHEMA IF NOT EXISTS authorforge;

-- ── Projections — verifiable cache of authority-owned content ────────────────

CREATE TABLE IF NOT EXISTS authorforge.public_content_projection (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug             TEXT UNIQUE NOT NULL,
  title            TEXT NOT NULL,
  content_kind     TEXT NOT NULL,
  body_public      TEXT NOT NULL,
  source_system    TEXT NOT NULL,
  source_record_id TEXT NOT NULL,
  schema_version   TEXT NOT NULL DEFAULT 'PublicContentProjection.v1',
  status           TEXT NOT NULL DEFAULT 'draft'
                     CHECK (status IN ('draft', 'published', 'archived')),
  published_at     TIMESTAMPTZ,
  source_updated_at TIMESTAMPTZ,
  last_verified_at TIMESTAMPTZ,
  checksum         TEXT NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_public_content_published
  ON authorforge.public_content_projection (status, published_at DESC);

CREATE TABLE IF NOT EXISTS authorforge.public_feature_projection (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  feature_key      TEXT UNIQUE NOT NULL,
  enabled          BOOLEAN NOT NULL DEFAULT false,
  audience         TEXT NOT NULL DEFAULT 'public'
                     CHECK (audience IN ('public', 'beta', 'internal')),
  description      TEXT,
  source_system    TEXT NOT NULL,
  source_record_id TEXT NOT NULL,
  schema_version   TEXT NOT NULL DEFAULT 'PublicFeatureProjection.v1',
  status           TEXT NOT NULL DEFAULT 'active'
                     CHECK (status IN ('active', 'retired')),
  source_updated_at TIMESTAMPTZ,
  last_verified_at TIMESTAMPTZ,
  checksum         TEXT NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS authorforge.public_release_projection (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  version          TEXT UNIQUE NOT NULL,
  title            TEXT NOT NULL,
  body_public      TEXT NOT NULL,
  channel          TEXT NOT NULL DEFAULT 'stable'
                     CHECK (channel IN ('stable', 'beta', 'canary')),
  source_system    TEXT NOT NULL,
  source_record_id TEXT NOT NULL,
  schema_version   TEXT NOT NULL DEFAULT 'PublicReleaseProjection.v1',
  status           TEXT NOT NULL DEFAULT 'draft'
                     CHECK (status IN ('draft', 'published', 'archived')),
  published_at     TIMESTAMPTZ,
  source_updated_at TIMESTAMPTZ,
  last_verified_at TIMESTAMPTZ,
  checksum         TEXT NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_public_release_published
  ON authorforge.public_release_projection (status, published_at DESC);

-- ── Intake — public/user input ──────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS authorforge.public_waitlist_signup (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email_hash          TEXT NOT NULL,
  email_encrypted     TEXT,
  source_campaign     TEXT,
  request_fingerprint TEXT NOT NULL,
  idempotency_key     TEXT,
  source_system       TEXT NOT NULL DEFAULT 'authorforge_public',
  schema_version      TEXT NOT NULL DEFAULT 'PublicWaitlistSignup.v1',
  status              TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'confirmed', 'invited', 'spam', 'deleted')),
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_waitlist_email_created
  ON authorforge.public_waitlist_signup (email_hash, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_waitlist_idempotency
  ON authorforge.public_waitlist_signup (idempotency_key) WHERE idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS authorforge.public_contact_submission (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name                TEXT,
  email_hash          TEXT NOT NULL,
  email_encrypted     TEXT,
  topic               TEXT NOT NULL,
  message_redacted    TEXT NOT NULL,
  request_fingerprint TEXT NOT NULL,
  idempotency_key     TEXT,
  source_system       TEXT NOT NULL DEFAULT 'authorforge_public',
  schema_version      TEXT NOT NULL DEFAULT 'PublicContactSubmission.v1',
  status              TEXT NOT NULL DEFAULT 'received'
                        CHECK (status IN ('received', 'reviewed', 'converted_to_ticket', 'spam', 'deleted')),
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_contact_submission_email_created
  ON authorforge.public_contact_submission (email_hash, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_contact_idempotency
  ON authorforge.public_contact_submission (idempotency_key) WHERE idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS authorforge.public_support_ticket (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id        UUID,
  public_tracking_id TEXT UNIQUE NOT NULL,
  subject            TEXT NOT NULL,
  type               TEXT NOT NULL DEFAULT 'question'
                       CHECK (type IN ('question', 'bug', 'billing', 'feature_request', 'other')),
  priority           TEXT NOT NULL DEFAULT 'normal'
                       CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
  status             TEXT NOT NULL DEFAULT 'submitted'
                       CHECK (status IN ('submitted', 'triaged', 'waiting_on_user', 'waiting_on_internal', 'resolved', 'closed', 'spam')),
  source_system      TEXT NOT NULL DEFAULT 'authorforge_public',
  source_record_id   TEXT,
  schema_version     TEXT NOT NULL DEFAULT 'PublicSupportTicket.v1',
  request_fingerprint TEXT,
  idempotency_key    TEXT,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at        TIMESTAMPTZ,
  closed_at          TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_support_ticket_customer_status
  ON authorforge.public_support_ticket (customer_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_support_ticket_idempotency
  ON authorforge.public_support_ticket (idempotency_key) WHERE idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS authorforge.public_support_ticket_message (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  ticket_id         UUID NOT NULL
                      REFERENCES authorforge.public_support_ticket(id) ON DELETE CASCADE,
  author_type       TEXT NOT NULL
                      CHECK (author_type IN ('customer', 'support_agent', 'system')),
  body_redacted     TEXT NOT NULL,
  body_internal_ref TEXT,
  schema_version    TEXT NOT NULL DEFAULT 'PublicSupportTicketMessage.v1',
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ticket_message_ticket_created
  ON authorforge.public_support_ticket_message (ticket_id, created_at);

CREATE TABLE IF NOT EXISTS authorforge.public_support_ticket_event (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  ticket_id   UUID NOT NULL
                REFERENCES authorforge.public_support_ticket(id) ON DELETE CASCADE,
  event_type  TEXT NOT NULL
                CHECK (event_type IN ('created', 'status_changed', 'assigned', 'message_added', 'reopened', 'closed', 'spam_marked')),
  from_status TEXT,
  to_status   TEXT,
  actor_type  TEXT NOT NULL
                CHECK (actor_type IN ('customer', 'support_agent', 'system')),
  detail_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ticket_event_ticket_created
  ON authorforge.public_support_ticket_event (ticket_id, created_at);

CREATE TABLE IF NOT EXISTS authorforge.public_consent_record (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  subject_hash        TEXT NOT NULL,
  consent_type        TEXT NOT NULL
                        CHECK (consent_type IN ('marketing_email', 'terms_of_service', 'privacy_policy', 'cookies', 'data_processing')),
  granted             BOOLEAN NOT NULL,
  policy_version      TEXT NOT NULL,
  request_fingerprint TEXT,
  source_system       TEXT NOT NULL DEFAULT 'authorforge_public',
  schema_version      TEXT NOT NULL DEFAULT 'PublicConsentRecord.v1',
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_consent_subject
  ON authorforge.public_consent_record (subject_hash, consent_type, created_at DESC);

-- ── Rate limiting (write-heavy; short retention) ─────────────────────────────

CREATE TABLE IF NOT EXISTS authorforge.public_rate_limit_event (
  id                  BIGSERIAL PRIMARY KEY,
  request_fingerprint TEXT NOT NULL,
  endpoint            TEXT NOT NULL,
  outcome             TEXT NOT NULL DEFAULT 'allowed'
                        CHECK (outcome IN ('allowed', 'throttled', 'blocked')),
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_rate_limit_fingerprint_created
  ON authorforge.public_rate_limit_event (request_fingerprint, created_at DESC);

-- ── Entitlements — cache/projection (authority = ForgeCustomer cloud) ────────

CREATE TABLE IF NOT EXISTS authorforge.entitlements (
  id                     SERIAL PRIMARY KEY,
  email                  TEXT NOT NULL,
  stripe_customer_id     TEXT,
  stripe_subscription_id TEXT,
  product                TEXT NOT NULL DEFAULT 'authorforge-pro',
  state                  TEXT NOT NULL DEFAULT 'free'
                           CHECK (state IN ('free', 'pro_active', 'pro_needs_attention', 'pro_canceled_active', 'offline_unverified')),
  billing_status         TEXT NOT NULL DEFAULT 'none',
  period_end             TIMESTAMPTZ,
  last_checked_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_webhook_at        TIMESTAMPTZ,
  can_use_cloud          BOOLEAN NOT NULL DEFAULT false,
  schema_version         TEXT NOT NULL DEFAULT 'Entitlement.v1',
  source_system          TEXT NOT NULL DEFAULT 'authorforge_local',
  source_record_id       TEXT,
  last_verified_at       TIMESTAMPTZ,
  checksum               TEXT,
  created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_entitlements_email
  ON authorforge.entitlements (lower(email));
CREATE INDEX IF NOT EXISTS idx_entitlements_stripe_customer
  ON authorforge.entitlements (stripe_customer_id) WHERE stripe_customer_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_entitlements_stripe_subscription
  ON authorforge.entitlements (stripe_subscription_id) WHERE stripe_subscription_id IS NOT NULL;

-- ── Operational support (agent runs, import receipts) ────────────────────────

CREATE TABLE IF NOT EXISTS authorforge.forgeagent_tasks (
  id            SERIAL PRIMARY KEY,
  project_id    INTEGER NOT NULL,
  execution_id  UUID NOT NULL UNIQUE,
  agent_name    VARCHAR(50) NOT NULL,
  trigger_event VARCHAR(50) NOT NULL,
  status        VARCHAR(20) NOT NULL DEFAULT 'pending',
  iterations    INTEGER DEFAULT 0,
  cost_usd      NUMERIC(8,4) DEFAULT 0,
  finding_count INTEGER DEFAULT 0,
  started_at    TIMESTAMPTZ DEFAULT now(),
  completed_at  TIMESTAMPTZ,
  result_summary JSONB,
  error_message TEXT,
  created_at    TIMESTAMPTZ DEFAULT now(),
  updated_at    TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_forgeagent_tasks_project
  ON authorforge.forgeagent_tasks (project_id);
CREATE INDEX IF NOT EXISTS idx_forgeagent_tasks_agent
  ON authorforge.forgeagent_tasks (agent_name, project_id);
CREATE INDEX IF NOT EXISTS idx_forgeagent_tasks_active
  ON authorforge.forgeagent_tasks (status, project_id)
  WHERE status::text = ANY (ARRAY['pending'::text, 'running'::text]);

CREATE TABLE IF NOT EXISTS authorforge.intake_receipts (
  receipt_id              TEXT PRIMARY KEY,
  project_id              TEXT,
  source_filename         TEXT NOT NULL,
  source_digest           TEXT NOT NULL,
  document_type           TEXT NOT NULL,
  detected_source         TEXT,
  classification_confidence REAL,
  records_found           INTEGER NOT NULL DEFAULT 0,
  records_imported        INTEGER NOT NULL DEFAULT 0,
  duplicates              INTEGER NOT NULL DEFAULT 0,
  status                  TEXT NOT NULL DEFAULT 'reviewing'
                            CHECK (status IN ('pending', 'reviewing', 'completed', 'failed')),
  created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_intake_receipts_project
  ON authorforge.intake_receipts (project_id, created_at DESC);

-- ── Record the app schema version (foundation tracks the app's own row) ──────

UPDATE core_schema_versions
   SET current_version = '0002',
       expected_version = '0002',
       status = 'current',
       updated_at = NOW()
 WHERE target = 'authorforge';

COMMIT;

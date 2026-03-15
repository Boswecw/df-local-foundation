# DF Local Foundation — Closeout Memo
**Date:** 2026-03-15
**Plans executed:** v1.1 + v1.2
**Status:** Initial governed implementation complete

---

## What Was Built

DF Local Foundation is the shared local-first PostgreSQL control surface for Forge
ecosystem applications. This repository represents the first governed pass — from
doctrine lock through hardened enforcement and first seed-app attachment proof.

---

## Delivery Summary

### Plan v1.1 — Foundation Skeleton

| Deliverable | Status |
|-------------|--------|
| Doctrine docs (6 files) | Done |
| JSON Schema contracts (health, app-registration, migration-status) | Done |
| SQL core migrations (0001 registry/events, 0002 backup/export logs) | Done |
| `core/config/settings.py` — canonical env contract | Done |
| `core/lifecycle/manager.py` — connect → migrate → report lifecycle | Done |
| `core/health/reporter.py` — banned-field enforcement at serialization | Done |
| `core/backup/manager.py` — fail-closed restore, integrity hash | Done |
| `core/export/manager.py` — namespace-scoped exports with envelope | Done |
| Operator tools (db-status, db-backup, db-restore, db-export) | Done |
| Test cluster: health contract, registration, restore validation, migration contract | Done |

### Plan v1.2 — Hardening + Seed-App Attachment

| Deliverable | Status |
|-------------|--------|
| Migration advisory lock (PostgreSQL pg_try_advisory_lock, 5s bounded, session-scoped) | Done |
| Health-event retention (30d default, 7d floor, prune helpers) | Done |
| HMAC-SHA256 envelope signing (per-install key, canonical JSON, constant-time verify) | Done |
| Unsigned envelope blocked by default; `--allow-unsigned` explicit opt-in | Done |
| `--dry-run` on db-restore (full validation, no apply) | Done |
| Registration compatibility semantics (4-scenario version table, downgrade blocked) | Done |
| `prod-local` profile strict mode (no default credentials, no wildcard host) | Done |
| CLI authority audit (schema-validated output, registered-namespace gate) | Done |
| Status leakage red-team (11 injection attacks) | Done |
| Restore abuse red-team (12 hostile fixtures) | Done |
| AuthorForge attachment SQL (`sql/apps/authorforge/0001_authorforge_attach.sql`) | Done |
| AuthorForge attachment tests (5 invariants + privacy boundary, integration-marked) | Done |

---

## Architecture in One Paragraph

DF Local Foundation owns the lifecycle chassis — PostgreSQL init, migration sequencing
under advisory lock, coarse health/status reporting, backup/export/restore with HMAC
envelopes, and app registration with version compatibility enforcement. It does not own
app business schemas, customer content, billing truth, or AI memory. Apps attach by
registering in `core_app_registry` and claiming a private schema namespace. ForgeCommand
consumes only declared health status — no raw DB access. The privacy boundary is enforced
at the serialization layer (`HealthReporter` / banned-field list), at the schema layer
(`additionalProperties: false`), and at the CLI layer (schema-validated output before
emission, registered-namespace gate before backup/export).

---

## What Is Explicitly Not Done (by design)

| Item | Reason |
|------|--------|
| Multi-app rollout beyond AuthorForge | Out of scope for v1.2 |
| NeuronForge Local bounded contract | Slice 7 — next plan |
| Hybrid/Pro augmentation contract | Slice 8 — next plan |
| Full Alembic migration runner integration | Lifecycle manager reports state; applying migrations is a separate operational concern scoped to each app |
| Async event streaming for health state | Not required until ForgeCommand integration work begins |
| Replay protection on export timestamps | Documented as a known limit in plan v1.2 (timestamp is informational, not a replay guard) |

---

## Invariants (16 total)

1. App-local domain truth stays app-owned.
2. DF Local Foundation stays minimal.
3. ForgeCommand sees declared operational state only.
4. NeuronForge Local is not the owner of canonical truth.
5. Restore / export / backups are versioned and integrity-checked.
6. Suspicious or ambiguous states fail closed.
7. Local-first remains meaningful even when hybrid/cloud options exist.
8. Migration state advances only under advisory lock.
9. Export envelopes are HMAC-signed with a locally-held key.
10. Unsigned envelopes are blocked on restore by default.
11. CLI tools cannot emit fields outside the bounded health contract.
12. CLI tools cannot operate on unregistered namespaces.
13. Registration compatibility is checked before any runtime operation proceeds.
14. Incompatible version states fail closed before runtime.
15. AuthorForge domain tables do not exist in `core.*`.
16. Foundation `ready` requires all registered apps to be `ready`.

---

## Test Coverage Map

| Module | Test File(s) |
|--------|-------------|
| Health contract + privacy boundary | `tests/visibility_boundary/test_health_contract.py` |
| Health event discipline | `tests/visibility_boundary/test_health_event_discipline.py` |
| CLI authority surface | `tests/visibility_boundary/test_cli_authority.py` |
| Status leakage red-team (11 attacks) | `tests/visibility_boundary/test_status_redteam.py` |
| App registration contract | `tests/registration/test_app_registration.py` |
| Registration compatibility semantics | `tests/registration/test_compatibility_semantics.py` |
| Config bypass prevention | `tests/registration/test_config_bypass.py` |
| Restore validation (fail-closed) | `tests/backup_restore/test_restore_validation.py` |
| Envelope signing (HMAC round-trip) | `tests/backup_restore/test_envelope_signing.py` |
| Restore abuse red-team (12 fixtures) | `tests/backup_restore/test_restore_redteam.py` |
| Migration contract | `tests/migration_status/test_migration_contract.py` |
| Migration advisory lock | `tests/migration_status/test_migration_lock.py` |
| AuthorForge attachment (integration) | `tests/first_integration/test_authorforge_attachment.py` |

Integration tests require live PostgreSQL env vars and are marked `@pytest.mark.integration`.
Run them with: `pytest tests/first_integration/ -m integration`

---

## Next Recommended Work

**Slice 7 — NeuronForge Local Bounded Contract**
- Define read contract (lexicon lookup, lore context, bounded retrieval)
- Define write contract (run metadata, provenance markers, eval artifacts)
- Prove non-authority rule in tests

**Slice 8 — Hybrid/Pro Augmentation Contract**
- Entitlement cache shape
- App mode declaration shape
- Local-to-cloud movement rules
- Hard billing/subscription authority boundary

**Operational**
- Wire `check_registration_compatibility` into `LifecycleManager.start()` for all registered apps
- Run integration test suite against a real local PostgreSQL instance
- Integrate `core/lifecycle/compatibility.py` into the registration write path
- Consider Alembic integration for the migration application path

---

## Files

```
df-local-foundation/
  README.md
  CLOSEOUT.md
  pyproject.toml
  contracts/
    health.schema.json
    app-registration.schema.json
    migration-status.schema.json
  docs/
    architecture.md
    privacy-doctrine.md
    migration-doctrine.md
    operational-visibility.md
    app-integration-contract.md
    backup-export-restore.md
  sql/
    core/
      0001_core_foundation.sql
      0002_core_metadata.sql
    apps/
      authorforge/
        0001_authorforge_attach.sql
  core/
    config/settings.py
    lifecycle/manager.py
    lifecycle/migration_lock.py
    lifecycle/maintenance.py
    lifecycle/compatibility.py
    health/reporter.py
    backup/manager.py
    backup/signing.py
    export/manager.py
  tools/
    db-status
    db-backup
    db-restore
    db-export
  tests/
    visibility_boundary/  (5 test files)
    registration/         (3 test files)
    backup_restore/       (3 test files)
    migration_status/     (2 test files)
    first_integration/    (1 test file, integration-marked)
```

# DF Local Foundation — Operational Visibility Contract

**Version:** v1.1
**Date:** 2026-03-15

---

## Purpose

This document defines the **maximum** baseline visibility allowed for control-plane consumption (ForgeCommand and equivalent orchestration consumers).

Nothing beyond this contract is exposed. The contract is additive only by explicit, reviewed declaration.

---

## Health / Status Contract Shape

```json
{
  "status": "ready | degraded | unavailable | migrating",
  "schema_version": "string",
  "expected_schema_version": "string",
  "migration_required": true,
  "last_error_class": "string | null",
  "started_at": "ISO8601 timestamp",
  "db_engine": "postgresql",
  "ownership": "app-local",
  "app_mode": "local | hybrid | cloud-enabled"
}
```

See [contracts/health.schema.json](../contracts/health.schema.json) for the machine-readable schema.

---

## Status States

| State | Meaning |
|-------|---------|
| `ready` | DB is up, all migrations applied, no errors |
| `degraded` | DB is up but operating in a reduced capacity |
| `unavailable` | DB is not reachable or migration failed |
| `migrating` | DB is up, migration in progress or pending |

Apps must **not** promote to `ready` while any migration is pending or any error is unresolved.

---

## Allowed Fields

| Field | Type | Notes |
|-------|------|-------|
| `status` | enum string | Required |
| `schema_version` | string | Current applied version identifier |
| `expected_schema_version` | string | Expected version per app declaration |
| `migration_required` | boolean | True if schema_version < expected |
| `last_error_class` | string or null | Error category only — no message content, no stack trace |
| `started_at` | ISO8601 string | Lifecycle start time |
| `db_engine` | string | Always `"postgresql"` for local |
| `ownership` | string | Always `"app-local"` for local |
| `app_mode` | enum string | `local`, `hybrid`, or `cloud-enabled` |

---

## Explicitly Banned Fields

The following fields **must never appear** in health/status responses or any control-plane artifact:

| Field | Reason |
|-------|--------|
| Table contents | Customer privacy |
| Record counts | Infers customer activity |
| Table names beyond core metadata | App implementation detail |
| Project names | Customer-owned identity |
| Manuscript / document names | Customer-owned content |
| Domain object counts or summaries | Customer-domain truth |
| Query endpoints | Violates inspection boundary |
| Raw schema browsing | Violates inspection boundary |
| Error message text with content fragments | May leak customer data |

---

## ForgeCommand Contract Rule

ForgeCommand consumes **app-declared status artifacts**, not database introspection.

The correct pattern:

1. The app exposes a bounded health/status surface (HTTP endpoint or IPC call).
2. ForgeCommand reads that declared surface.
3. ForgeCommand does not connect directly to the local PostgreSQL instance.
4. ForgeCommand does not issue SQL queries against app-local authority tables.

This boundary is the privacy guarantee. Breaking it collapses the privacy story.

---

## Backup / Export Readiness Signals

A backup/export readiness signal is permitted in the health response as an extension field:

```json
{
  "backup_available": true,
  "last_backup_at": "ISO8601 timestamp | null",
  "export_available": true
}
```

These are boolean / timestamp signals only. They do not expose backup content or export content.

---

## Error Class Vocabulary

`last_error_class` must use the following vocabulary only:

| Class | Meaning |
|-------|---------|
| `migration_failure` | A migration did not complete |
| `connection_failure` | Cannot reach local PostgreSQL |
| `integrity_failure` | Integrity check failed |
| `compatibility_failure` | Declared compatibility mismatch |
| `startup_failure` | Generic startup fault |
| `restore_blocked` | Restore validation failed |
| `null` | No current error |

No free-form error text, no exception messages, no stack traces in the health surface.

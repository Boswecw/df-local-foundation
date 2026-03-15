# DF Local Foundation — Migration Doctrine

**Version:** v1.1
**Date:** 2026-03-15

---

## Migration Tool

The foundation uses **Alembic** (Python) as the canonical migration tool for core migrations.

Apps manage their own migrations within their own schema namespace using the same tool.

---

## Naming Rules

Core migrations:

```
sql/core/NNNN_description.sql
```

Where `NNNN` is a zero-padded integer sequence (e.g., `0001`, `0002`).

App migrations (in the app repo):

```
migrations/YYYYMMDD_HHMMSS_description.sql
```

Apps must not use the `core_` schema namespace prefix.

---

## Execution Order Rules

1. Core foundation migrations run first on startup.
2. App migrations run after core migrations complete successfully.
3. Partial migration state is reported as `migrating` — never `ready`.
4. Any migration failure halts startup and reports `unavailable`.

---

## Startup Migration Posture

On process start:

1. Connect to local PostgreSQL.
2. Check `core_schema_versions` for pending core migrations.
3. If pending: apply in sequence, fail closed on any error.
4. Report final state via health contract.

**Do not silently skip failed migrations.** A migration failure is a hard stop.

---

## Schema Version Reporting

Schema version is reported in the health contract as:

```json
{
  "schema_version": "0002",
  "expected_schema_version": "0002",
  "migration_required": false
}
```

If `schema_version` < `expected_schema_version`, status is `migrating` (or `unavailable` if migration cannot proceed).

---

## Rollback Posture

Foundation core migrations are designed to be forward-only. Rollback is an operator action requiring:

1. Manual intervention with explicit confirmation
2. A restore from backup where appropriate
3. Validation that the rolled-back state passes integrity checks

**There is no automatic rollback.** Silent rollback hides failures.

---

## App Schema Attachment

Apps attach their own schema to the same PostgreSQL instance by:

1. Declaring their schema namespace in `core_app_registry`
2. Running their own migrations against their own namespace
3. Reporting their own schema version through their registration record

The foundation does not run, own, or inspect app-level migrations.

---

## Invalid States

| State | Classification | Response |
|-------|---------------|---------|
| Core migration pending at startup | `migrating` | Apply migrations or fail |
| Core migration error | `unavailable` | Halt; surface error class |
| Schema version mismatch (pending) | `migrating` | Block `ready` promotion |
| Unknown migration version | `unavailable` | Fail closed |
| App declares incompatible core version | Reject registration | Log as fault |

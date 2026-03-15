# DF Local Foundation — App Integration Contract

**Version:** v1.1
**Date:** 2026-03-15

---

## Overview

Apps attach to DF Local Foundation using an **app-owned schema attachment model**.

The foundation provides the lifecycle chassis. Each app owns its own domain schema, migrations, and business truth. The attachment model proves that apps can use the foundation without surrendering domain authority.

---

## App Registration

Apps register by inserting into `core_app_registry` at first startup.

See [contracts/app-registration.schema.json](../contracts/app-registration.schema.json) for the machine-readable contract.

### Required Registration Fields

| Field | Type | Description |
|-------|------|-------------|
| `app_id` | string | Stable lowercase identifier (e.g., `authorforge`) |
| `app_version` | string | Semver string of the registering app |
| `foundation_version_required` | string | Minimum foundation version this app requires |
| `schema_namespace` | string | PostgreSQL schema name owned by this app (e.g., `authorforge`) |
| `app_mode` | enum | `local \| hybrid \| cloud-enabled` |
| `registered_at` | ISO8601 | Registration timestamp |

### Optional Registration Fields

| Field | Type | Description |
|-------|------|-------------|
| `entitlement_snapshot` | object | Cached Pro/hybrid feature state (non-authoritative) |
| `last_validated_at` | ISO8601 | When entitlement was last validated against cloud |
| `enabled_features` | array | Snapshot of enabled feature flags |

---

## Compatibility Declaration

An app declares compatibility with a foundation version range at registration time.

If the running foundation version falls outside the declared range:
- Registration is **rejected**
- Status surfaces report `unavailable` or `degraded` as appropriate
- The event is logged to `core_health_events`

**Incompatible registration is a hard stop, not a soft warning.**

---

## Schema Namespace Rules

1. Apps use a dedicated PostgreSQL schema matching their `app_id`.
2. Apps must not write to the `core_*` namespace.
3. Apps must not read from another app's namespace.
4. Foundation does not inspect or own app schema tables.

Example namespace for AuthorForge:

```sql
CREATE SCHEMA IF NOT EXISTS authorforge;
-- All AuthorForge tables live in authorforge.*
-- Foundation has no visibility into authorforge.manuscripts, etc.
```

---

## Migration Integration

Apps manage their own migrations within their namespace.

At startup:

1. Foundation runs core migrations first.
2. App runs its own namespace migrations after.
3. Each app reports its own schema version via `core_schema_versions`.
4. Foundation health reports the union state: `ready` only when all registered apps are ready.

---

## Health Surface per App

Each app must expose a health artifact conforming to [contracts/health.schema.json](../contracts/health.schema.json).

This is the **only** surface the control plane consumes. No direct DB access.

---

## First Integration: AuthorForge (Seed)

AuthorForge is the seed app for proving the attachment model. The integration must demonstrate:

1. AuthorForge registers with `app_id: "authorforge"` and `schema_namespace: "authorforge"`
2. AuthorForge runs its own migrations under `authorforge.*`
3. Foundation lifecycle start/status surfaces work correctly
4. AuthorForge health endpoint exposes only the declared fields
5. No AuthorForge domain tables (manuscripts, lore, etc.) appear in foundation core
6. ForgeCommand can read health state without accessing AuthorForge tables

The seed integration does not generalize AuthorForge patterns to other apps. It proves the model.

---

## Anti-Patterns to Reject

| Pattern | Why Rejected |
|---------|-------------|
| App puts business tables in `core_*` namespace | Violates app authority rule |
| Foundation queries app schema tables | Violates privacy boundary |
| App registration silently degrades on mismatch | Violates fail-closed rule |
| App declares a compatibility range that includes a broken foundation version | Must be caught at registration |
| Two apps share a schema namespace | Schema isolation violation |

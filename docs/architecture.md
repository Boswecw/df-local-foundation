# DF Local Foundation — Architecture

**Version:** v1.1
**Date:** 2026-03-15

---

## Purpose

DF Local Foundation is the **shared local-first PostgreSQL control surface** for Forge ecosystem applications.

Its job is to give Forge apps a shared local data discipline while preserving:

- app-owned authority over domain truth
- privacy-first operation (customer content stays local by default)
- bounded operational visibility (control-plane consumers see only declared state)
- disciplined lifecycle, migration, and backup posture

---

## What DF Local Foundation Owns

| Concern | Owned by Foundation |
|---------|-------------------|
| Local PostgreSQL lifecycle (init/start/stop/status) | Yes |
| Readiness checks | Yes |
| Degraded / unavailable / migrating classification | Yes |
| Canonical env variable names and config conventions | Yes |
| Migration tooling choice and execution rules | Yes |
| Schema version tracking | Yes |
| Health / status contract shape | Yes |
| Backup convention | Yes |
| Export metadata envelope | Yes |
| Restore validation rules | Yes |
| App registration and compatibility shape | Yes |
| Shared core SQL (`core_*` tables) | Yes (minimal set only) |

---

## What DF Local Foundation Does Not Own

| Concern | Owned by |
|---------|---------|
| Manuscript / document content | AuthorForge |
| Lore / world-building entities | AuthorForge |
| Campaign / outreach business tables | App-specific |
| Market / watchlist / strategy entities | App-specific |
| Project / workspace domain truth | Each owning app |
| App-specific review / promotion semantics | Each owning app |
| Billing / subscription authority | ForgeCommand / cloud |
| AI memory or provenance canon | Not any single local layer |

---

## System Diagram

```
┌─────────────────────────────────────────────────────────┐
│                    ForgeCommand                          │
│         (declared status only — no raw DB access)       │
└─────────────┬───────────────────────────────────────────┘
              │ health / readiness / migration state
              │ (bounded visibility contract)
┌─────────────▼───────────────────────────────────────────┐
│               DF Local Foundation                        │
│    (lifecycle · migration · health · backup/export)      │
└──────┬──────────────────────────────────┬───────────────┘
       │ schema attachment                │ bounded contracts
┌──────▼──────┐                  ┌───────▼────────────────┐
│ App Schema  │                  │  NeuronForge Local      │
│ (app-owned) │                  │  (bounded read/write    │
│             │                  │   — never truth owner)  │
└─────────────┘                  └────────────────────────┘
```

---

## Shared Core Surface (Minimal)

Only tables that justify themselves as **cross-app discipline** belong in the shared core.

Allowed:

| Table | Purpose |
|-------|---------|
| `core_app_registry` | Registered apps and compatibility declarations |
| `core_schema_versions` | Migration tracking per app |
| `core_backup_log` | Audit log of backup operations |
| `core_export_log` | Audit log of export operations |
| `core_health_events` | Coarse health transition log |

Rejected from core: anything that is business meaning for a specific app.

---

## App Attachment Model

Apps attach to DF Local Foundation by:

1. Registering in `core_app_registry` (app ID, version, compatibility declaration, mode)
2. Owning their own schema namespace (e.g., `authorforge.*`)
3. Managing their own migrations within their namespace
4. Declaring readiness via the health contract

The foundation does not own or control app-domain schemas. It provides the lifecycle surface that apps run on top of.

---

## App Modes

| Mode | Meaning |
|------|---------|
| `local` | Customer data stays fully local, no cloud sync |
| `hybrid` | Local authority with optional cloud augmentation |
| `cloud-enabled` | Cloud features active, local remains authoritative for domain data |

---

## Design Biases

- **Fewer shared tables** over more
- **Coarse health signals** over detailed introspection
- **Fail closed** on ambiguous state
- **Explicit operator actions** over silent background operations
- **Declared contracts** over inspection

---

## Non-Goals (Permanent)

- Making DF Local the billing or entitlement authority
- Giving ForgeCommand customer-data introspection powers
- Turning NeuronForge Local into canonical memory owner
- Replacing DataForge cloud responsibilities
- Building a "one schema to rule them all" abstraction layer

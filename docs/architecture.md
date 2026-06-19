# DataForge Local Foundation Architecture

**Status:** source authority baseline.
**Scope:** local-system proving repo.

## Role

DataForge Local is the local durable-truth substrate for Forge systems. It owns
local substrate structure, registry records, migration posture, service status,
lineage/proving records, and bounded operational visibility.

It does not own product-domain meaning, customer content, entitlement authority,
or application-specific review/promote workflows.

## Ownership Boundary

| Concern | DataForge Local posture |
| --- | --- |
| Local PostgreSQL schemas and migrations | Owned for DataForge Local schemas |
| Service/schema registry records | Owned as local substrate metadata |
| Readiness, migration, degradation, fault class | Owned as status metadata |
| Application domain data | Not owned |
| ForgeCommand orchestration | Observed through bounded status, not raw DB access |
| AI model/provider choice | Not owned |

## Current Proof Surfaces

- `doc/system/` and generated `doc/DLOSYSTEM.md` are the canonical code mirror.
- `alembic/versions/` is the migration source.
- `app/api/*_router.py` exposes bounded API surfaces.
- `tests/` and `tests/proving_slice/` prove deterministic local behavior.

## Design Rule

Prefer explicit local records over inference. When status is ambiguous,
DataForge Local reports blocked, degraded, or unavailable posture instead of
inventing readiness.

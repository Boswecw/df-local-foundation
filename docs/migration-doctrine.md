# DataForge Local Migration Doctrine

**Status:** source authority baseline.
**Scope:** local-system proving repo.

## Canonical Tooling

DataForge Local uses Alembic migrations under `alembic/versions/`.

## Current Proof Surfaces

- `alembic/env.py` defines offline and online migration execution.
- `alembic/versions/20260402_02_create_substrate_core_tables.py` creates
  `migration_registry`.
- `alembic/versions/20260402_04_create_service_status_tables.py` exposes
  `migration_required` and `compatibility_blocked` status fields.

## Rules

- Migration state must be explicit.
- Pending or failed migrations must not be reported as ready.
- Migration failures must preserve an operator-visible error class.
- Application-specific domain migrations remain app-owned unless explicitly
  admitted into DataForge Local.

## Promotion Boundary

The support copy may reference migration posture and Alembic as source-backed
truth. Exact app migration path conventions require app-specific proof before
promotion.

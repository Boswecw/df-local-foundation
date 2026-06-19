# DataForge Local App Integration Contract

**Status:** source authority baseline.
**Scope:** local-system proving repo.
**Promotion rule:** app-support copies may quote this file only after drift
reports show this source path present and current.

## Contract

Applications attach to DataForge Local through declared service/schema records.
DataForge Local owns the substrate, service registry, status, migration, and
readiness posture. Application repos own domain schema, domain data, business
meaning, and user-facing workflows.

## Required Attachment Posture

- Each app has a stable service identity in the service registry.
- App-owned schema state is represented through schema and migration registry
  records, not through implicit table inspection.
- Compatibility or migration blockers must surface as blocked/degraded status,
  not as silent partial readiness.
- DataForge Local must not become the authority for app-domain truth.

## Current Proof Surfaces

- `alembic/versions/20260402_02_create_substrate_core_tables.py` creates
  `schema_registry` and `migration_registry`.
- `alembic/versions/20260402_03_create_service_registry_tables.py` creates the
  service registry.
- `alembic/versions/20260402_04_create_service_status_tables.py` creates current
  and historical service status, fault, recovery, and backup posture tables.
- `app/api/public_applications_router.py` exposes public application ownership
  records without making DataForge Local the product authority.

## Not Yet Proven Here

The support copy describes concrete `core_app_registry` field names. This source
repo currently proves the broader service/schema registry posture under the
substrate and service schemas. A future migration may add exact app-attachment
field names; until then, support docs must not claim those exact names as source
truth.

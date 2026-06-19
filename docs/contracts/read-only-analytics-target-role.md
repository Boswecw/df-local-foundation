# DF Local Read-Only Analytics Target Role

## Status

Target role opened; runtime, routes, models, migrations, and schema not promoted.

## Source Authority

The local-system proving repo at
`/home/charlie/Forge/ecosystem/local-systems/dataforge-Local` owns the current
read-only analytics endpoint contract, typed response models, service layer, and
proof.

Current source authority evidence:

- `doc/plans/local-analytics/df_local_analytics_slice_01.md`
- `app/api/analytics_router.py`
- `app/analytics_models.py`
- `app/analytics_services.py`
- `tests/api/test_analytics_routes.py`
- `tests/api/test_analytics_compute.py`

## Target Role

DF Local app support may receive a future read-only analytics promotion only as
the bounded app-support visibility side of the local-system analytics substrate.

The support target role is limited to:

- exposing derived local-system analytics payloads
- preserving `_derived: true` and `schema_version: v1`
- preserving freshness and staleness labels
- keeping analytics endpoints read-only
- surfacing degraded or stale state explicitly
- avoiding ownership of app-domain truth, customer truth, billing truth, or AI
  memory truth

## Explicit Non-Goals

This target role does not authorize:

- copying analytics routes, models, services, migrations, or tests in this slice
- adding write endpoints under the analytics namespace
- treating derived analytics as canonical app-domain records
- silently hiding stale, partial, or degraded status
- adding cloud promotion behavior
- changing AuthorForge, ForgeCommand, or other app workflows
- storing durable GNAT or semantic-candidate records in DF Local support

## Promotion Gate

Before any read-only analytics file is promoted into app support, the promotion
slice must name:

- exact files to promote
- source proof command
- support proof command
- support service contract or adapter target
- post-promotion drift report
- rollback path

Until that gate exists, read-only analytics runtime and schema remain
`source_local_hold` in the promotion ledger.

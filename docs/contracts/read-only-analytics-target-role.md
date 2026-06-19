# DF Local Read-Only Analytics Target Role

## Status

Runtime role active for the bounded read-only analytics surface. Models, compute
logic, and routes are promoted as support-native adapters. Migrations remain
outside this promotion.

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

## Active Support Role

DF Local app support may receive a future read-only analytics promotion only as
the bounded app-support visibility side of the local-system analytics substrate.

The support role is limited to:

- exposing derived local-system analytics payloads
- preserving `_derived: true` and `schema_version: v1`
- preserving freshness and staleness labels
- keeping analytics endpoints read-only
- surfacing degraded or stale state explicitly
- avoiding ownership of app-domain truth, customer truth, billing truth, or AI
  memory truth

## Explicit Non-Goals

This target role does not authorize:

- adding write endpoints under the analytics namespace
- treating derived analytics as canonical app-domain records
- silently hiding stale, partial, or degraded status
- adding cloud promotion behavior
- changing AuthorForge, ForgeCommand, or other app workflows
- storing durable GNAT or semantic-candidate records in DF Local support
- promoting local-system analytics migrations into app support

## Promoted Support Files

The active support-native runtime lives in:

- `app/analytics_config.py`
- `app/analytics_models.py`
- `app/analytics_services.py`
- `app/api/analytics_router.py`
- `tests/api/test_analytics_compute.py`
- `tests/api/test_analytics_routes.py`

The router exposes only:

- `GET /api/v1/analytics/overview`
- `GET /api/v1/analytics/systems`
- `GET /api/v1/analytics/queue`
- `GET /api/v1/analytics/freshness`

If the foundation cannot read the analytics source tables, routes return an
explicit `503` with `error_class: analytics_read_failure`.

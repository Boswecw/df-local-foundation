# DataForge Local Operational Visibility Contract

**Status:** source authority baseline.
**Scope:** local-system proving repo.

## Purpose

Control-plane consumers may see bounded operational posture. They may not inspect
customer content, app-domain records, raw app table contents, or hidden business
meaning through DataForge Local.

## Allowed Status Classes

Source-backed visibility includes:

- service state
- readiness state
- degradation class
- last error class
- migration required
- compatibility blocked
- last recorded status timestamp
- backup/export/restore posture

## Current Proof Surfaces

- `service_status_current`
- `service_status_history`
- `service_fault_events`
- `service_recovery_events`
- `service_backup_posture`
- `app/analytics_services.py`
- `tests/api/test_analytics_routes.py`

## Banned Visibility

- table contents
- app-domain record counts unless explicitly declared as non-sensitive aggregate
- manuscript names, project names, customer text, or product-domain identifiers
- raw query surfaces for control-plane browsing
- provider/model secrets

## Rule

Expose classed posture, not content. If a field could reveal customer or
app-domain truth, it must remain outside the control-plane status contract.

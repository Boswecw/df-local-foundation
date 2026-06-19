# DataForge Local Backup, Export, And Restore Doctrine

**Status:** source authority baseline.
**Scope:** local-system proving repo.

## Doctrine

Backup, export, and restore posture is operator-visible metadata. It is not an
ambient guarantee and must not imply customer-content inspection by control
planes.

## Current Proof Surface

`alembic/versions/20260402_04_create_service_status_tables.py` creates
`service_backup_posture` with:

- `backup_ready`
- `export_ready`
- `restore_blocked`
- `restore_block_reason_class`
- `evaluated_at`

This proves readiness posture tracking. It does not yet prove a full payload
backup/export/restore engine.

## Required Rules

- Partial or failed backup/restore states must not be reported as complete.
- Restore blockers must preserve reason class without exposing app content.
- Operator-facing surfaces may expose readiness posture and reason classes.
- App-domain content remains app-owned.

## Promotion Boundary

Support docs may describe backup/export/restore as an operator doctrine. They
must not claim implemented payload backup/restore behavior unless source code and
tests prove that behavior in this repo.

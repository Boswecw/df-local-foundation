# DF Local Foundation — Backup / Export / Restore Doctrine

**Version:** v1.1
**Date:** 2026-03-15

---

## Doctrine

Backups are **operator actions**, not silent background guarantees.

Every backup, export, and restore operation is:
- explicit
- versioned
- integrity-checked
- logged to `core_backup_log` or `core_export_log`

There is no ambient backup agent that operates without operator knowledge.

---

## Backup Doctrine

### Requirements

- Backups are local-first
- Each backup carries a version envelope (app ID, foundation version, schema version, timestamp, format version)
- Backup integrity is verified via SHA-256 hash of the payload
- Backup log entry is written to `core_backup_log` after each successful backup

### Backup Envelope (Metadata)

```json
{
  "app_id": "string",
  "foundation_version": "string",
  "schema_version": "string",
  "backup_at": "ISO8601",
  "format_version": "1",
  "integrity_hash": "sha256:...",
  "includes_namespaces": ["core", "authorforge"]
}
```

### Failure Rules

If backup cannot complete:
- Do not write a partial backup as if it were complete
- Log the failure to `core_backup_log` with `status: "failed"`
- Surface error class to operator

---

## Export Doctrine

### Requirements

Exports declare:
- app identifier
- schema compatibility / version
- export timestamp
- format version
- integrity / hash metadata

### Export Envelope

```json
{
  "app_id": "string",
  "foundation_version": "string",
  "schema_version": "string",
  "export_at": "ISO8601",
  "format_version": "1",
  "integrity_hash": "sha256:...",
  "namespace": "authorforge"
}
```

---

## Restore Doctrine

### Pre-restore Validation (Mandatory)

Restore must validate before applying **any** changes:

| Check | Failure Response |
|-------|----------------|
| Integrity hash match | Block; report `integrity_failure` |
| Compatible app identity | Block; report `compatibility_failure` |
| Schema version compatibility | Block; report `compatibility_failure` |
| Expected foundation version | Block; report `compatibility_failure` |
| Format version supported | Block; report `compatibility_failure` |
| Operator intent confirmed | Block; require explicit confirmation flag |

All checks must pass. There is no partial validation.

### Fail-Closed Restore Rules

Restore is blocked if **any** of the following are true:

- Integrity hash mismatch
- Incompatible schema version
- Wrong app target
- Unsupported export format version
- Missing required metadata fields
- Foundation version mismatch outside declared compatibility range

### Restore Process

1. Parse and validate the backup/export envelope (all checks above).
2. Require operator confirmation (explicit flag, not implicit).
3. Create a pre-restore checkpoint backup.
4. Apply the restore.
5. Run integrity checks on the restored state.
6. If post-restore checks fail: roll back to checkpoint and surface error.
7. Log outcome to `core_backup_log`.

---

## Tool Contracts

| Tool | Inputs | Outputs |
|------|--------|---------|
| `db-backup` | `--app-id`, `--output-path` | Versioned backup file + log entry |
| `db-export` | `--app-id`, `--namespace`, `--output-path` | Versioned export file + log entry |
| `db-restore` | `--input-path`, `--confirm` | Restored DB state + log entry |
| `db-status` | (none) | Health/status JSON per [contract](operational-visibility.md) |

---

## Operator Safety Notes

1. Never restore over a live production database without a pre-restore checkpoint.
2. Export files are not encrypted by default — handle them as sensitive data.
3. Backup files should be stored outside the application data directory.
4. Restore should be tested in a non-production environment first.
5. The foundation does not auto-delete old backups — operator is responsible for retention.

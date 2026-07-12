# Forge · df-local-foundation

> **System identity — Forge family (public-app local support).**
> App-support local PostgreSQL control surface for Forge **public-facing applications**; part of `apps/public-app-local-support`.
> **Purpose:** owns lifecycle, migration-status reporting, coarse health/readiness, and backup/export/restore tooling for app-registered Postgres instances.
> **Not the bds counterpart:** the business-side local operator is `ecosystem/local-systems/dataforge-Local` (bds family).

DF Local Foundation is the app-support local PostgreSQL control surface for
Forge applications.

It owns lifecycle, migration-status reporting, coarse health/readiness,
backup/export/restore tooling, and app registration conventions. It does not
own app business schemas, customer domain truth, billing authority, or canonical
AI memory.

## Status

- Version: `v1.1`
- State: active app-support reference
- Closeout: `docs/closeout-initial-governed-implementation.md`

## Documentation

- `docs/architecture.md` - purpose, boundaries, and design rules
- `docs/privacy-doctrine.md` - privacy boundary
- `docs/migration-doctrine.md` - migration framework
- `docs/operational-visibility.md` - bounded status visibility
- `docs/app-integration-contract.md` - app registration and attachment
- `docs/contracts/read-only-analytics-target-role.md` - bounded read-only analytics support role
- `docs/contracts/local-api-target-roles.md` - remaining DF Local API target roles
- `docs/backup-export-restore.md` - backup/export/restore safety

## Code Mirror

`doc/system/` is the canonical code mirror. Rebuild the assembled mirror with:

```bash
bash doc/system/BUILD.sh
```

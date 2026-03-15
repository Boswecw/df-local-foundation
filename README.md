# DF Local Foundation

**Version:** v1.1
**Date:** 2026-03-15
**Status:** Active

---

## What This Is

DF Local Foundation is the **shared local PostgreSQL control surface** for Forge ecosystem applications.

It provides:

- disciplined local database lifecycle
- canonical migration and schema version reporting
- coarse health/readiness/status contracts
- backup / export / restore doctrine and tooling
- app registration and compatibility conventions
- bounded integration contracts for ForgeCommand and NeuronForge Local

It is **not** DataForge (the cloud persistence service).
It is **not** a universal business-schema repository.
It is **not** a control-plane inspection backdoor.

---

## What It Does Not Own

- App business schemas (manuscripts, lore, campaigns, watchlists, etc.)
- Customer domain truth of any kind
- Billing or subscription authority
- Any canonical memory surface for AI consumers

See [docs/privacy-doctrine.md](docs/privacy-doctrine.md) for the full boundary definition.

---

## Directory Structure

```
df-local-foundation/
  docs/                          # Doctrine and contract documentation
  contracts/                     # JSON Schema contracts
  sql/core/                      # Shared core SQL migrations
  core/
    lifecycle/                   # DB start / stop / status / readiness
    config/                      # Env contract and connection conventions
    health/                      # Health reporting surface
    backup/                      # Backup utilities
    export/                      # Export utilities
  tools/                         # Operator CLI tools
  tests/                         # Contract and boundary tests
```

---

## Tools

| Tool | Purpose |
|------|---------|
| `tools/db-status` | Report lifecycle status and migration state |
| `tools/db-backup` | Create a versioned local backup |
| `tools/db-restore` | Restore with integrity and compatibility checks |
| `tools/db-export` | Export with metadata envelope |

---

## Docs

| Document | Purpose |
|----------|---------|
| [architecture.md](docs/architecture.md) | System purpose, boundaries, and design rules |
| [privacy-doctrine.md](docs/privacy-doctrine.md) | Privacy boundary definition |
| [migration-doctrine.md](docs/migration-doctrine.md) | Migration framework and execution rules |
| [operational-visibility.md](docs/operational-visibility.md) | What control-plane consumers may see |
| [app-integration-contract.md](docs/app-integration-contract.md) | How apps attach and register |
| [backup-export-restore.md](docs/backup-export-restore.md) | Backup/export/restore safety rules |

---

## Invariants

1. App-local domain truth stays app-owned.
2. DF Local Foundation stays minimal.
3. ForgeCommand sees declared operational state only.
4. NeuronForge Local is not the owner of canonical truth.
5. Restore / export / backups are versioned and integrity-checked.
6. Suspicious or ambiguous states fail closed.
7. Local-first remains meaningful even when hybrid/cloud options exist.

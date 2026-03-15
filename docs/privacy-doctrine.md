# DF Local Foundation — Privacy Doctrine

**Version:** v1.1
**Date:** 2026-03-15

---

## Core Rule

**Customer and app-domain truth remains local by default.**

Cloud behavior is:
- additive
- selective
- opt-in where required
- explicitly policy-bound

There is no implicit sync, no ambient telemetry on content, and no control-plane visibility into customer-owned records.

---

## App Authority Rule

Each app owns its own:

- domain schema
- migrations beyond shared core attachment
- repository / service layer
- domain invariants
- promotion / review workflows
- customer-facing business meaning

DF Local Foundation supplies the chassis. It does not own the cargo.

---

## ForgeCommand Visibility Boundary

ForgeCommand is the orchestration layer. For DF Local, it receives a **strictly limited lane**.

### Allowed

| Signal | Description |
|--------|-------------|
| `status` | `ready \| degraded \| unavailable \| migrating` |
| `schema_version` | Current applied migration version |
| `expected_schema_version` | Expected migration version |
| `migration_required` | Boolean flag |
| `last_error_class` | Error category string, no content |
| `started_at` | Lifecycle start timestamp |
| `db_engine` | `postgresql` |
| `ownership` | `app-local` |
| `app_mode` | `local \| hybrid \| cloud-enabled` |
| Backup/export readiness signal | Boolean, no content |

### Never Allowed

| Signal | Reason |
|--------|--------|
| Table contents | Customer privacy |
| Record counts | Infers customer activity |
| Project names | Customer-owned identity |
| Manuscript names | Customer-owned content |
| Domain metadata | App-owned truth |
| Query surfaces | Violates inspection boundary |
| Raw table list browsing | Violates inspection boundary |

**Once this boundary is broken, the privacy story collapses. Fail closed.**

---

## NeuronForge Local Boundary

NeuronForge Local may interact with DF Local through declared contracts only.

### Allowed Read Contracts

- Project lexicon lookups (via app-declared view/endpoint)
- Lore / entity context lookups (via app-declared view/endpoint)
- Bounded retrieval / context assembly (via app-declared contract)
- Lane / prompt / profile references where app-appropriate

### Allowed Write Contracts

- Run metadata artifacts
- Provenance markers
- Evaluation artifacts
- Candidate outputs where domain-appropriate

### Explicit Non-Authority Rule

NeuronForge Local **does not own** canonical customer memory. It consumes and emits through bounded contracts. It must not build a parallel truth substrate because it is convenient for AI features.

---

## Fail-Closed Events

The following states must cause a fail-closed response — no silent promotion, no fallback:

| Trigger | Required Response |
|---------|------------------|
| Invalid migration state | Fail with `migrating` or `unavailable` status |
| Compatibility mismatch | Block registration; log as fault |
| Malformed app registration | Reject; do not partially register |
| Restore integrity mismatch | Block restore; require operator resolution |
| Unauthorized visibility expansion | Log as security event; deny request |
| Suspicious export/import payload | Block; surface for operator inspection |
| Unsupported schema attachment shape | Reject; do not attempt partial attachment |

---

## Hybrid / Pro Augmentation Boundary

Local-first remains meaningful even when an app offers Pro or cloud features.

| Truth Type | Stays |
|-----------|-------|
| Customer content | Local |
| Project / workspace authority | Local |
| Local operating state | Local |
| Billing truth | Cloud-authoritative |
| Subscription truth | Cloud-authoritative |
| Seat / license truth | Cloud-authoritative |
| Entitlement issuance / revocation | Cloud-authoritative |

A local entitlement cache (install reference, feature flag snapshot, last-validated timestamp) is permitted. It is a snapshot — the cloud is still authoritative.

**DF Local must never become the billing or subscription authority.**

---

## Enforcement Requirement

Privacy boundary tests are not optional. Every implementation slice that touches visibility surfaces must include tests that prove:

- No table contents are reachable via status/health surfaces
- No record counts are exposed
- No project or manuscript names are reachable
- ForgeCommand-facing artifacts contain only the declared field set

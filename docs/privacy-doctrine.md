# DataForge Local Privacy Doctrine

**Status:** source authority baseline.
**Scope:** local-system proving repo.

## Core Rule

Customer and app-domain truth remains local and app-owned by default.
DataForge Local may record substrate metadata, service status, lineage,
verification, and readiness posture, but it must not become a backdoor for
customer-content inspection.

## Authority Split

| Layer | Owns |
| --- | --- |
| DataForge Local | local substrate, registry, status, migration, lineage, proving metadata |
| App support repo | app-local support behavior and public-app integration copy |
| Product app | user workflow and domain truth |
| ForgeCommand | orchestration over declared status, not raw local-data inspection |

## Privacy Rules

- Default to content-minimized records.
- Preserve class/reason fields instead of raw content.
- Fail closed when visibility boundaries are ambiguous.
- Do not infer customer behavior from local substrate records.
- Do not expose app-owned schemas to orchestration consumers.

## Current Proof Surfaces

- Service status migrations expose classed fields rather than raw content.
- Public application records describe local-data ownership, not product-domain
  facts.
- Lineage/proving records are schema-versioned and reviewable.

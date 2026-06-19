# DF Local API Target Roles

## Status

Target roles opened for remaining DF Local source API candidates. The
public-applications, context-pack, and healing-proposals read-only lanes are
promoted as support-native adapters.
Other runtime, migrations, schemas, and write behavior are not promoted.

## Source Authority

The local-system proving repo at
`/home/charlie/Forge/ecosystem/local-systems/dataforge-Local` owns the current
source API behavior for:

- `app/api/context_pack_router.py`
- `app/api/healing_proposal_router.py`
- `app/api/lineage_router.py`
- `app/api/proving_slice_queue_router.py`
- `app/api/public_applications_router.py`
- `proving_slice/`
- `alembic/`

## Read-Only Candidate Lane

The following surface is active as a support-native read-only adapter:

- `GET /df/rag/context-pack/{context_pack_id}`
- `GET /api/v1/public-applications`
- `GET /api/v1/healing-proposals`
- `GET /api/v1/healing-proposals/{proposal_id}`

The following surfaces may be considered for future support-native read-only
adapter promotion:

- `GET /api/v1/lineage/nodes`
- `GET /api/v1/lineage/nodes/{node_id}`
- `GET /api/v1/lineage/nodes/{node_id}/downstream`
- `GET /api/v1/proving-slice/queue`
- `GET /api/v1/proving-slice/queue/{staged_promotion_id}`

Future promotion must adapt these to the support app's async foundation boundary,
keep them read-only, and return explicit unavailable/degraded status when the
source tables cannot be read.

## Durable Truth Hold Lane

The following source endpoints remain held because they mutate durable local
truth or require schema ownership proof:

- `POST /df/rag/context-pack`
- `POST /api/v1/healing-proposals`
- `PATCH /api/v1/healing-proposals/{proposal_id}`
- `POST /api/v1/lineage/nodes`
- `POST /api/v1/lineage/edges`
- `POST /api/v1/lineage/envelopes`

These are not support visibility adapters. They require a later promotion slice
that proves schema ownership, idempotency, authorization, rollback, and consumer
compatibility.

## Promotion Gate

Before any file is promoted, the slice must name:

- exact source and target files
- the selected lane and endpoint list
- source proof command
- support proof command
- migration/schema decision
- post-promotion drift report
- rollback path

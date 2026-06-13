## 8. API Layer

DF Local Foundation exposes a single **read-only HTTP health API** (`app/`, FastAPI). It is the
control-plane visibility surface for consumers such as ForgeCommand. It serves ONLY the declared
health surface (`contracts/health.schema.json`) — it never exposes customer data, table contents,
record counts, or any app's domain schema (e.g. `authorforge.*`).

The foundation is the **only** process permitted to connect to its database; the supporting
PostgreSQL instance is for the owning application's data. This API lets other services read coarse
foundation health without any direct database access of their own.

### 8.1 Endpoints

| Method | Path | DB? | Returns |
| --- | --- | --- | --- |
| GET | `/live` | no | Process liveness: `{ service, version, status: "live" }`. Never touches the database. |
| GET | `/health` | yes | `DFLocalHealthStatus` (per `contracts/health.schema.json`): `status` (ready/degraded/unavailable/migrating), `schema_version`, `expected_schema_version`, `migration_required`, `last_error_class`, `started_at`, `db_engine`, `ownership`, `app_mode`. Fails closed: reports `unavailable` when the database is unreachable. |

### 8.2 Implementation

- `app/main.py` — `create_app()` builds the FastAPI app; a lifespan connects the
  `LifecycleManager` once at startup and fails closed (logs, does not crash) if the database is
  down. `/health` flows through the existing `HealthReporter`, so the privacy boundary and JSON
  Schema contract validation are enforced at the serialization layer, not just the data layer.
- `app/__main__.py` — `python -m app` runs uvicorn on `DF_LOCAL_API_HOST:DF_LOCAL_API_PORT`.
- Optional dependency group: `pip install -e ".[api]"` (FastAPI + uvicorn). The core library and
  CLI tools do not require it.

### 8.3 Boundaries

- No mutation endpoints. No authentication is performed here — the surface carries no sensitive
  data and binds to a local address by configuration.
- The response shape is owned by `contracts/health.schema.json`; adding a field requires changing
  the contract first (see §6 Change Control).

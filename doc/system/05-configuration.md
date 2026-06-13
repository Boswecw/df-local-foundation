## 5. Configuration & Environment

Configuration is the canonical contract in `core/config/settings.py` (`FoundationSettings`,
pydantic-settings). All attaching apps must use these env variable names — do not invent
alternatives. Config is a hard-fail surface: invalid combinations raise on construction
(fail-closed), and the `prod-local` profile forbids default credentials and wildcard host binds.

### 5.1 Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `DF_LOCAL_HOST` | `127.0.0.1` | PostgreSQL host. |
| `DF_LOCAL_PORT` | `5432` | PostgreSQL port. |
| `DF_LOCAL_DB` | _(required)_ | Database name. |
| `DF_LOCAL_USER` | _(required)_ | Database user. |
| `DF_LOCAL_PASSWORD` | _(required)_ | Database password. |
| `DF_LOCAL_DATA_DIR` | `/var/lib/df-local` | Data directory. |
| `DF_LOCAL_APP_ID` | _(required)_ | Owning app identifier (must not be `core`). |
| `DF_LOCAL_APP_MODE` | `local` | `local` \| `hybrid` \| `cloud-enabled`. |
| `DF_LOCAL_PROFILE` | `dev` | `dev` \| `test` \| `prod-local` (strict rules in prod-local). |
| `DF_LOCAL_API_HOST` | `127.0.0.1` | Bind host for the read-only health API (`app/`, §8). |
| `DF_LOCAL_API_PORT` | `8099` | Bind port for the health API. |

### 5.2 Notes

- `DF_LOCAL_API_HOST` / `DF_LOCAL_API_PORT` are consumed by `python -m app` (the health API).
  They are part of the canonical settings contract so the API surface is configured the same way
  as the rest of the foundation; `prod-local` host-binding rules apply to `DF_LOCAL_HOST`.
- Connection strings are derived in `FoundationSettings` (`connection_string` /
  `async_connection_string`); apps and tools must not assemble their own.

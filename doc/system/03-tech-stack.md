## 3. Tech Stack

This baseline stack inventory is inferred from repository markers and directory layout.

### 3.1 Stack

| Layer | Technology |
| --- | --- |
| Language | Python ≥ 3.11 |
| Database driver | `asyncpg` (PostgreSQL) |
| Config / validation | `pydantic` v2 + `pydantic-settings`; `jsonschema` for contract validation |
| HTTP health API (optional, `app/`) | `fastapi` + `uvicorn` — install via `".[api]"` |
| Tests / lint / types | `pytest` + `pytest-asyncio`, `ruff`, `mypy` (dev extra) |

The core library and CLI tools require only the base dependencies; FastAPI/uvicorn are an optional
extra needed solely to run the health API (`python -m app`).

"""PyInstaller entrypoint for the DF Local Foundation control-surface sidecar.

AuthorForge (and other Forge desktop apps) launch the foundation as a Tauri-
managed sidecar — a single frozen binary. uvicorn is handed the FastAPI app
*object* (not the ``"app.main:app"`` import string), so the frozen binary never
depends on re-importing ``app.main`` from a writable source tree at runtime.

Host/port come from the canonical settings contract
(``DF_LOCAL_API_HOST`` / ``DF_LOCAL_API_PORT``); loading settings up front
fails fast on invalid configuration, exactly like ``python -m app``.
"""

from __future__ import annotations

import uvicorn

from app.main import app
from core.config.settings import load_settings


def main() -> None:
    settings = load_settings()
    uvicorn.run(
        app,
        host=settings.df_local_api_host,
        port=settings.df_local_api_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()

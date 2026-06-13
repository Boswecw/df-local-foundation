"""Run the DF Local Foundation health API.

    python -m app

Host/port come from the canonical settings contract (DF_LOCAL_API_HOST / DF_LOCAL_API_PORT).
Loading settings up front fails fast on invalid configuration.
"""

from __future__ import annotations

import uvicorn

from core.config.settings import load_settings


def main() -> None:
    settings = load_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.df_local_api_host,
        port=settings.df_local_api_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()

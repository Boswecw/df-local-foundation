"""DF Local Foundation — read-only HTTP health API.

A thin ASGI surface over the existing lifecycle/health layer. It serves ONLY the declared
control-plane health surface (contracts/health.schema.json) — never customer data, table
contents, or domain metadata. The foundation is the sole process that touches its own
database; this endpoint lets control-plane consumers (e.g. ForgeCommand) read coarse health
without any direct database access of their own.

Endpoints:
  GET /live     Process liveness (never touches the database).
  GET /health   Database-aware foundation health (DFLocalHealthStatus contract).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request

from app.analytics_services import AsyncpgAnalyticsReader
from app.api.analytics_router import register_analytics_routes
from app.api.context_pack_router import register_context_pack_routes
from app.api.healing_proposal_router import register_healing_proposal_routes
from app.api.lineage_router import register_lineage_routes
from app.api.proving_slice_queue_router import register_proving_slice_queue_routes
from app.api.public_applications_router import register_public_applications_routes
from app.context_pack_services import AsyncpgContextPackReader
from app.healing_proposal_services import AsyncpgHealingProposalReader
from app.lineage_services import AsyncpgLineageReader
from app.proving_slice_queue_services import AsyncpgProvingSliceQueueReader
from app.public_applications_services import AsyncpgPublicApplicationsReader
from core.config.settings import FOUNDATION_VERSION, load_settings
from core.health.reporter import HealthReporter
from core.lifecycle.manager import LifecycleManager, LifecycleStartError

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Connect the lifecycle once at startup; fail closed (not crash) if the database is down.

    A connection failure is caught here so `/health` can honestly report `unavailable` rather
    than the process failing to boot. Configuration errors (invalid settings) remain a hard stop.
    """
    settings = load_settings()
    lifecycle = LifecycleManager(settings)
    try:
        await lifecycle.start()
    except LifecycleStartError as exc:
        logger.warning("df_local.api.start_degraded error_class=%s", exc.error_class.value)
    app.state.lifecycle = lifecycle
    app.state.reporter = HealthReporter(lifecycle)
    app.state.analytics_reader = AsyncpgAnalyticsReader(settings.connection_string)
    app.state.context_pack_reader = AsyncpgContextPackReader(settings.connection_string)
    app.state.healing_proposal_reader = AsyncpgHealingProposalReader(settings.connection_string)
    app.state.lineage_reader = AsyncpgLineageReader(settings.connection_string)
    app.state.proving_slice_queue_reader = AsyncpgProvingSliceQueueReader(
        settings.connection_string
    )
    app.state.public_applications_reader = AsyncpgPublicApplicationsReader(settings.connection_string)
    try:
        yield
    finally:
        await lifecycle.stop()


def get_reporter(request: Request) -> HealthReporter:
    """Resolve the request-scoped health reporter. Overridable in tests."""
    return request.app.state.reporter


def create_app(
    lifespan_factory: Callable[[FastAPI], AbstractAsyncContextManager[None]] = lifespan,
) -> FastAPI:
    """Build the FastAPI app. `lifespan_factory` is injectable so tests can avoid the database."""
    app = FastAPI(
        title="DF Local Foundation",
        version=FOUNDATION_VERSION,
        summary="Read-only control-plane health surface. No customer or domain data is exposed.",
        lifespan=lifespan_factory,
    )

    @app.get("/live")
    async def live() -> dict[str, Any]:
        # Pure process liveness — deliberately does not touch the database.
        return {"service": "df-local-foundation", "version": FOUNDATION_VERSION, "status": "live"}

    @app.get("/health")
    async def health(reporter: Annotated[Any, Depends(get_reporter)]) -> dict[str, Any]:
        # DB-aware foundation health, validated against contracts/health.schema.json by the reporter.
        response = await reporter.get_health()
        return response.to_dict()

    register_analytics_routes(app)
    register_context_pack_routes(app)
    register_healing_proposal_routes(app)
    register_lineage_routes(app)
    register_proving_slice_queue_routes(app)
    register_public_applications_routes(app)

    return app


app = create_app()

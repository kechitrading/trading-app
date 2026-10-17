"""FastAPI app factory: ``uvicorn aqta.api:create_app --factory``."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from aqta.api.container import Container, build_container
from aqta.api.errors import install_error_handlers
from aqta.api.middleware import RequestIdMiddleware
from aqta.api.routers import health, v1
from aqta.core.logs import configure_logging, get_logger
from aqta.core.settings import Settings, get_settings

log = get_logger(__name__)


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or (container.settings if container else get_settings())
    configure_logging(settings.log_level, json=settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owned = container is None
        app.state.container = container or build_container(settings)
        c: Container = app.state.container
        await c.audit.record(
            "api.started",
            {"mode": settings.trading_mode.value, "env": settings.app_env.value},
            "system",
        )
        log.info("api.started", mode=settings.trading_mode.value, env=settings.app_env.value)
        try:
            yield
        finally:
            if owned:
                await c.close()

    app = FastAPI(
        title="AQTA - AI Quant Trading Assistant",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if settings.app_env == "prod" else "/docs",
        redoc_url=None,
        openapi_url=None if settings.app_env == "prod" else "/openapi.json",
    )
    if container is not None:
        app.state.container = container  # available before lifespan for test clients
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,  # empty by default: no cross-origin access
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )
    app.add_middleware(RequestIdMiddleware)
    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(v1.router)
    return app

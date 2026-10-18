"""FastAPI app factory: ``uvicorn aqta.api:create_app --factory``."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from aqta.api.actions import ContainerBotActions
from aqta.api.container import Container, build_container
from aqta.api.errors import install_error_handlers
from aqta.api.middleware import RequestIdMiddleware
from aqta.api.routers import health, v1
from aqta.core.logs import configure_logging, get_logger
from aqta.core.settings import Settings, get_settings
from aqta.notifications import build_dispatcher

log = get_logger(__name__)

BotPoller = tuple[Any, "asyncio.Task[None]"]


def start_bot(container: Container) -> BotPoller | None:
    """Poll Telegram from this process (FR-023, FR-034). Outbound only: no public webhook."""
    s = container.settings
    if container.telegram_bot is None or not s.telegram_polling:
        return None
    dp = build_dispatcher(s, ContainerBotActions(container))
    task = asyncio.create_task(
        dp.start_polling(container.telegram_bot, handle_signals=False, close_bot_session=False)
    )
    log.info("telegram.polling_started")
    return dp, task


async def stop_bot(poller: BotPoller | None) -> None:
    if poller is None:
        return
    dp, task = poller
    with contextlib.suppress(RuntimeError):  # polling may not have started yet
        await dp.stop_polling()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or (container.settings if container else get_settings())
    configure_logging(settings.log_level, json=settings.log_json)
    show_docs = settings.app_env != "prod" or settings.docs_enabled

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
        poller = start_bot(c)
        try:
            yield
        finally:
            await stop_bot(poller)
            if owned:
                await c.close()

    app = FastAPI(
        title="AQTA - AI Quant Trading Assistant",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if show_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if show_docs else None,
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

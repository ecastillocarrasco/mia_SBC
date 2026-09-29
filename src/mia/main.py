"""Aplicación FastAPI: ``uvicorn --factory mia.main:create_app``."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from mia import __version__
from mia.api.errors import install_error_handlers
from mia.api.middleware import RequestContextMiddleware
from mia.api.routes import admin, chat, compat, documents, health, mail, reports, voice
from mia.api.routes.frontend import mount_frontend
from mia.api.services import Services
from mia.data.schema import schema_problem
from mia.observability import configure_logging, get_logger
from mia.observability.telemetry import configure_telemetry
from mia.settings import Settings, VoiceProviderName, get_settings

log = get_logger(__name__)


async def _warm_voice(services: Services) -> None:
    if services.settings.voice.provider is VoiceProviderName.NONE:
        return
    try:
        count = await services.voice.warm(services.engine.persona.fixed_phrases())
        log.info("voice.warmed", phrases=count)
    except Exception as exc:  # la voz nunca impide arrancar
        log.warning("voice.warm_failed", error=str(exc))


def create_app(settings: Settings | None = None, services: Services | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.observability.log_level, settings.observability.log_json)
    configure_telemetry(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.services = services or Services.build(settings)
        warm = asyncio.create_task(_warm_voice(app.state.services))
        log.info("app.started", version=__version__, environment=settings.environment.value)
        if problem := await schema_problem(app.state.services.db):
            log.error("app.migrations_pending", detail=problem)
        try:
            yield
        finally:
            warm.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await warm
            await app.state.services.aclose()

    app = FastAPI(title="mIA", version=__version__, lifespan=lifespan)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
    )
    install_error_handlers(app)
    for router in (
        health.router,
        chat.router,
        voice.router,
        reports.router,
        documents.router,
        admin.router,
        compat.router,
        mail.router,
    ):
        app.include_router(router)
    mount_frontend(app, settings.frontend)
    return app

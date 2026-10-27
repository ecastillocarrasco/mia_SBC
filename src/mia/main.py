"""Aplicación FastAPI: ``uvicorn --factory mia.main:create_app``."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from mia import __version__, diagnostics
from mia.api.errors import install_error_handlers
from mia.api.middleware import RequestContextMiddleware
from mia.api.routes import (
    admin,
    attachments,
    auth,
    chat,
    community,
    compat,
    documents,
    health,
    jobs,
    mail,
    reports,
    voice,
)
from mia.api.routes.frontend import mount_frontend
from mia.api.services import Services
from mia.conversation.retention import run_retention_cleanup
from mia.data.retention import run_audit_retention_cleanup
from mia.data.schema import schema_problem
from mia.diagnostics.routes import router as diagnostics_router
from mia.diagnostics.store import DiagnosticsStore
from mia.diagnostics.streaming import LiveBroadcaster
from mia.modules.rrhh.informes.jobs import JOB_KIND_INFORME_ECONOMICO, run_informe_economico_nominas
from mia.observability import configure_logging, get_logger
from mia.observability.telemetry import configure_telemetry
from mia.reporting.retention import run_report_cleanup
from mia.reporting.worker import ReportJobWorker
from mia.settings import Settings, VoiceProviderName, get_settings

log = get_logger(__name__)


def _start_retention_tasks(
    services: Services, settings: Settings
) -> tuple[asyncio.Task, asyncio.Task, asyncio.Task | None]:
    conversations = asyncio.create_task(run_retention_cleanup(services.db, settings.conversation_retention_days))
    audit = asyncio.create_task(run_audit_retention_cleanup(services.db, settings.audit_retention_days))
    reports = (
        asyncio.create_task(run_report_cleanup(services.db, services.report_storage, settings.reports.directory))
        if services.report_storage is not None
        else None
    )
    return conversations, audit, reports


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
        retention_cleanup, audit_cleanup, report_cleanup = _start_retention_tasks(app.state.services, settings)

        # Diagnóstico — solo si está habilitado
        diag_store: DiagnosticsStore | None = None
        if settings.diagnostics.enabled:
            diag_store = DiagnosticsStore(settings.diagnostics)
            broadcaster = LiveBroadcaster()
            diagnostics.setup(diag_store, broadcaster, mask_pii=settings.diagnostics.mask_pii)
            diag_store.start_cleanup()
            log.info("diagnostics.enabled", max_traces=settings.diagnostics.max_traces)

        if settings.attachments.enabled and app.state.services.attachment_service is not None:
            app.state.services.attachment_service.start_cleanup()
            log.info("attachments.enabled", max_file_mb=settings.attachments.max_file_mb)

        job_worker: ReportJobWorker | None = None
        if settings.jobs.enabled:
            job_worker = ReportJobWorker(
                app.state.services,
                {JOB_KIND_INFORME_ECONOMICO: run_informe_economico_nominas},
                poll_interval_seconds=settings.jobs.poll_interval_seconds,
                lease_seconds=settings.jobs.lease_seconds,
            )
            job_worker.start()
            log.info("jobs.worker_started", lease_seconds=settings.jobs.lease_seconds)

        warm = asyncio.create_task(_warm_voice(app.state.services))
        log.info("app.started", version=__version__, environment=settings.environment.value)
        if problem := await schema_problem(app.state.services.db):
            log.error("app.migrations_pending", detail=problem)
        try:
            yield
        finally:
            if report_cleanup is not None:
                report_cleanup.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await report_cleanup
            retention_cleanup.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await retention_cleanup
            audit_cleanup.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await audit_cleanup
            warm.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await warm
            if job_worker is not None:
                await job_worker.aclose()
            if diag_store:
                await diag_store.aclose()
            await app.state.services.aclose()

    app = FastAPI(title="mIA", version=__version__, lifespan=lifespan)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
    )
    install_error_handlers(app)
    for router in (
        health.router,
        auth.router,
        chat.router,
        voice.router,
        reports.router,
        jobs.router,
        documents.router,
        community.router,
        admin.router,
        diagnostics_router,
        compat.router,
        mail.router,
        attachments.router,
    ):
        app.include_router(router)
    mount_frontend(app, settings.frontend)
    return app

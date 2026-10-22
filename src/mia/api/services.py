"""Contenedor de servicios de la aplicación (una instancia por proceso)."""

from __future__ import annotations

from dataclasses import dataclass

from mia.attachments.service import AttachmentService
from mia.auth import IdentityProvider, build_identity_provider
from mia.connectors.graph import GraphClient
from mia.connectors.sharepoint import CertificateTokenProvider, SharePointClient
from mia.conversation import ConversationEngine, Persona, ToolRegistry
from mia.data import Database
from mia.ingestion.sync.factory import build_sharepoint_client
from mia.llm import LLMProvider, build_llm_provider
from mia.modules import community, finanzas, it
from mia.modules.rrhh import build_registry
from mia.modules.rrhh.correo.mailbox import mailbox_available, resolve_mailbox
from mia.settings import Settings
from mia.voice import CachedVoice, build_voice


def build_graph_client(settings: Settings) -> GraphClient | None:
    """Graph para el correo: misma aplicación y certificado que SharePoint."""
    if (
        "correo" not in settings.domains.enabled
        or not mailbox_available(settings.mail)
        or not settings.sharepoint.configured
    ):
        return None
    return GraphClient(CertificateTokenProvider(settings.sharepoint, scope="https://graph.microsoft.com/.default"))


@dataclass(slots=True)
class Services:
    settings: Settings
    db: Database
    llm: LLMProvider
    voice: CachedVoice
    identity: IdentityProvider
    engine: ConversationEngine
    registry: ToolRegistry
    """Mismo registro que usa `engine` — expuesto para quien necesite ejecutar una herramienta fuera de
    una conversación (p. ej. el ejecutor de trabajos del Job Manager, Fase G)."""
    graph: GraphClient | None = None
    sharepoint: SharePointClient | None = None
    attachment_service: AttachmentService | None = None

    @classmethod
    def build(
        cls,
        settings: Settings,
        *,
        llm: LLMProvider | None = None,
        voice: CachedVoice | None = None,
        db: Database | None = None,
    ) -> Services:
        database = db or Database(settings.database_url)
        provider = llm or build_llm_provider(settings.llm, settings.privacy_gateway)
        graph = build_graph_client(settings)
        sharepoint = build_sharepoint_client(settings) if settings.sharepoint.configured else None
        registry = build_registry(
            database,
            settings.data.stale_after_minutes,
            settings=settings,
            llm=provider,
            graph=graph,
            sharepoint=sharepoint,
            enabled=settings.domains.enabled,
        )
        finanzas.register(registry, None)
        it.register(registry, None)
        community.register(registry, settings, database)

        # Adjuntos: construir servicio e inyectar herramientas si está activo
        attachment_svc: AttachmentService | None = None
        if settings.attachments.enabled:
            from mia.attachments.tools import register as register_attachment_tools  # noqa: PLC0415
            attachment_svc = AttachmentService.build(settings, provider)
            register_attachment_tools(registry, attachment_svc)

        engine = ConversationEngine(
            llm=provider,
            tools=registry,
            db=database,
            persona=Persona(),
            mailbox_for=lambda user: resolve_mailbox(settings.mail, user),
            timezone=settings.timezone,
            history_turns=settings.history_turns,
            max_tool_rounds=settings.llm.max_tool_rounds,
            turn_budget_seconds=settings.llm.turn_budget_seconds,
            max_output_tokens=settings.llm.max_output_tokens,
        )
        return cls(
            settings=settings,
            db=database,
            llm=provider,
            voice=voice or build_voice(settings.voice),
            identity=build_identity_provider(settings.auth),
            engine=engine,
            registry=registry,
            graph=graph,
            sharepoint=sharepoint,
            attachment_service=attachment_svc,
        )

    async def aclose(self) -> None:
        if self.attachment_service is not None:
            await self.attachment_service.aclose()
        await self.llm.aclose()
        await self.voice.aclose()
        if self.graph is not None:
            await self.graph.aclose()
        if self.sharepoint is not None:
            await self.sharepoint.aclose()
        close_identity = getattr(self.identity, "aclose", None)
        if close_identity is not None:
            await close_identity()  # EntraIdIdentityProvider cierra su cliente HTTP del JWKS
        await self.db.dispose()

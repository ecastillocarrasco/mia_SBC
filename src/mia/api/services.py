"""Contenedor de servicios de la aplicación (una instancia por proceso)."""

from __future__ import annotations

from dataclasses import dataclass

from mia.auth import IdentityProvider, build_identity_provider
from mia.connectors.graph import GraphClient
from mia.connectors.sharepoint import CertificateTokenProvider, SharePointClient
from mia.conversation import ConversationEngine, Persona
from mia.data import Database
from mia.ingestion.sync.factory import build_sharepoint_client
from mia.llm import LLMProvider, build_llm_provider
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
    graph: GraphClient | None = None
    sharepoint: SharePointClient | None = None

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
        provider = llm or build_llm_provider(settings.llm)
        graph = build_graph_client(settings)
        sharepoint = build_sharepoint_client(settings) if settings.sharepoint.configured else None
        engine = ConversationEngine(
            llm=provider,
            tools=build_registry(
                database,
                settings.data.stale_after_minutes,
                settings=settings,
                llm=provider,
                graph=graph,
                sharepoint=sharepoint,
                enabled=settings.domains.enabled,
            ),
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
            graph=graph,
            sharepoint=sharepoint,
        )

    async def aclose(self) -> None:
        await self.llm.aclose()
        await self.voice.aclose()
        if self.graph is not None:
            await self.graph.aclose()
        if self.sharepoint is not None:
            await self.sharepoint.aclose()
        await self.db.dispose()

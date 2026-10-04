"""Contenedor de servicios de la aplicación (una instancia por proceso)."""

from __future__ import annotations

from dataclasses import dataclass

from mia.auth import IdentityProvider, build_identity_provider
from mia.conversation import ConversationEngine, Persona
from mia.data import Database
from mia.llm import LLMProvider, build_llm_provider
from mia.modules.rrhh import build_registry
from mia.settings import Settings
from mia.voice import CachedVoice, build_voice


@dataclass(slots=True)
class Services:
    settings: Settings
    db: Database
    llm: LLMProvider
    voice: CachedVoice
    identity: IdentityProvider
    engine: ConversationEngine

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
        engine = ConversationEngine(
            llm=provider,
            tools=build_registry(database),
            db=database,
            persona=Persona(),
            timezone=settings.timezone,
            history_turns=settings.history_turns,
            max_tool_rounds=settings.llm.max_tool_rounds,
            max_output_tokens=settings.llm.max_output_tokens,
        )
        return cls(
            settings=settings,
            db=database,
            llm=provider,
            voice=voice or build_voice(settings.voice),
            identity=build_identity_provider(settings.auth),
            engine=engine,
        )

    async def aclose(self) -> None:
        await self.llm.aclose()
        await self.voice.aclose()
        await self.db.dispose()

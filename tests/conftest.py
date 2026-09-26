from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from pathlib import Path

import httpx
import pytest

from mia.api.services import Services
from mia.data import Base, Database
from mia.llm.base import LLMEvent, LLMRequest
from mia.llm.fake import FakeLLMProvider, final_answer
from mia.main import create_app
from mia.settings import Environment, LLMProviderName, Settings
from mia.voice import CachedVoice, NullVoiceProvider

Script = Callable[[LLMRequest], list[LLMEvent]]


def make_settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": Environment.TEST,
        "database_url": f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        "llm": {"provider": LLMProviderName.FAKE},
        "observability": {"log_json": False, "log_level": "WARNING"},
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def script() -> list[Script]:
    """Guion del LLM falso; cada test lo sustituye si lo necesita."""
    return [lambda req: final_answer("Hola, soy mIA.", "¡Hola! Soy mIA. ¿En qué te ayudo?", "saludando")]


@pytest.fixture
async def services(settings: Settings, script: list[Script]) -> AsyncIterator[Services]:
    db = Database(settings.database_url)
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    llm = FakeLLMProvider(lambda req: script[0](req))  # noqa: PLW0108  (lee el guion vigente)
    built = Services.build(settings, llm=llm, db=db, voice=CachedVoice(NullVoiceProvider()))
    yield built
    await built.aclose()


@pytest.fixture
async def client(settings: Settings, services: Services) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings, services=services)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            yield http

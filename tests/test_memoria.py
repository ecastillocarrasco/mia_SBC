"""Memoria Inteligente V1: recuerdos manuales por usuario, aislados entre usuarios.

Cubre, a nivel de herramienta/repositorio (rápido, sin HTTP): el interruptor global, el
interruptor por usuario (desactivada por defecto, recuerdos previos conservados hasta borrarlos),
el guardado/listado/borrado por lenguaje natural, el límite por usuario y el aislamiento entre
usuarios. A nivel de motor: la recuperación pasiva entre turnos (contexto del LLM) respeta ambos
interruptores. A nivel de API: el control visual (encender/apagar, listar, borrar).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest

from mia.auth import UserContext
from mia.conversation import ToolRegistry
from mia.conversation.tools import ToolContext
from mia.data.repositories import MemoryRepository
from mia.llm import ToolCall
from mia.main import create_app
from mia.modules import memoria
from mia.settings import MemorySettings, Settings
from tests.conftest import make_settings
from tests.dbutil import fresh_database

NOW = datetime(2026, 11, 1, 10, 0, tzinfo=ZoneInfo("Europe/Madrid"))
ANA = UserContext("ana", "Ana", roles=frozenset({"mia.admin"}))
LUIS = UserContext("luis", "Luis", roles=frozenset({"mia.admin"}))


async def call(registry: ToolRegistry, name: str, user: UserContext = ANA, **args: Any) -> Any:
    ctx = ToolContext(user=user, request_id=None, now=NOW, session_state={})
    return (await registry.execute(ToolCall("c", name, json.dumps(args)), ctx)).result


@pytest.fixture
async def env(tmp_path: Path) -> Any:
    db = await fresh_database(tmp_path, "memoria.db")
    settings = Settings(memory=MemorySettings(enabled=True, max_items_per_user=2))
    registry = ToolRegistry()
    memoria.register(registry, settings, db)
    yield registry, db
    await db.dispose()


async def test_memory_disabled_globally_registers_no_tools(tmp_path: Path) -> None:
    db = await fresh_database(tmp_path, "off.db")
    settings = Settings(memory=MemorySettings(enabled=False))
    registry = ToolRegistry()
    memoria.register(registry, settings, db)
    assert registry.names() == []
    await db.dispose()


async def test_memory_enabled_globally_registers_the_five_tools(env: Any) -> None:
    registry, _ = env
    assert registry.names() == ["ajustar_memoria", "olvidar_recuerdo", "olvidar_todo", "recordar", "ver_recuerdos"]


async def test_recordar_does_nothing_until_the_user_activates_memory(env: Any) -> None:
    registry, db = env
    result = await call(registry, "recordar", contenido="que prefiero los informes en PDF")
    assert "desactivada" in result.summary
    async with db.session() as session:
        assert await MemoryRepository(session).list_memories(ANA.user_id) == []


async def test_activating_then_recordar_and_ver_recuerdos(env: Any) -> None:
    registry, _ = env
    await call(registry, "ajustar_memoria", activar=True)
    await call(registry, "recordar", contenido="que mi reunión de equipo es los jueves")
    result = await call(registry, "ver_recuerdos")
    assert result.summary["recuerdos"][0]["contenido"] == "que mi reunión de equipo es los jueves"
    assert result.presentation["rows"][0][0] == "que mi reunión de equipo es los jueves"


async def test_olvidar_recuerdo_matches_by_natural_language_without_accents_or_case(env: Any) -> None:
    registry, _ = env
    await call(registry, "ajustar_memoria", activar=True)
    await call(registry, "recordar", contenido="que prefiero los informes en PDF")
    await call(registry, "recordar", contenido="que mi cumpleaños es en marzo")
    miss = await call(registry, "olvidar_recuerdo", contenido="vacaciones")
    assert miss.status.value == "not_found"
    hit = await call(registry, "olvidar_recuerdo", contenido="CUMPLEANOS")  # sin tilde y en mayúsculas
    assert "1 recuerdo" in hit.summary
    remaining = await call(registry, "ver_recuerdos")
    assert len(remaining.summary["recuerdos"]) == 1
    assert "PDF" in remaining.summary["recuerdos"][0]["contenido"]


async def test_olvidar_todo_requires_explicit_confirmation(env: Any) -> None:
    registry, _ = env
    await call(registry, "ajustar_memoria", activar=True)
    await call(registry, "recordar", contenido="algo que recordar")
    unconfirmed = await call(registry, "olvidar_todo", confirmar=False)
    assert "No se ha borrado" in unconfirmed.summary
    assert len((await call(registry, "ver_recuerdos")).summary["recuerdos"]) == 1
    confirmed = await call(registry, "olvidar_todo", confirmar=True)
    assert "Borrados 1" in confirmed.summary
    assert (await call(registry, "ver_recuerdos")).summary == "No hay ningún recuerdo guardado todavía."


async def test_per_user_limit_is_enforced_without_erroring(env: Any) -> None:
    registry, _ = env  # max_items_per_user=2 en el fixture
    await call(registry, "ajustar_memoria", activar=True)
    await call(registry, "recordar", contenido="recuerdo uno")
    await call(registry, "recordar", contenido="recuerdo dos")
    at_limit = await call(registry, "recordar", contenido="recuerdo tres")
    assert at_limit.status.value == "ok"
    assert "máximo" in at_limit.summary
    assert len((await call(registry, "ver_recuerdos")).summary["recuerdos"]) == 2


async def test_two_users_never_see_each_others_memories(env: Any) -> None:
    registry, _ = env
    await call(registry, "ajustar_memoria", ANA, activar=True)
    await call(registry, "recordar", ANA, contenido="secreto de ana")
    # Luis nunca activó la memoria ni guardó nada: su propio interruptor está desactivado.
    luis_view = await call(registry, "ver_recuerdos", LUIS)
    assert luis_view.summary == "La memoria está desactivada: no hay recuerdos activos que mostrar."
    await call(registry, "ajustar_memoria", LUIS, activar=True)
    luis_view_enabled = await call(registry, "ver_recuerdos", LUIS)
    assert luis_view_enabled.summary == "No hay ningún recuerdo guardado todavía."
    ana_view = await call(registry, "ver_recuerdos", ANA)
    assert ana_view.summary["recuerdos"][0]["contenido"] == "secreto de ana"


async def test_disabling_memory_keeps_existing_items_until_explicit_deletion(env: Any) -> None:
    registry, db = env
    await call(registry, "ajustar_memoria", activar=True)
    await call(registry, "recordar", contenido="recuerdo que se conserva")
    await call(registry, "ajustar_memoria", activar=False)
    # No se ve ni se usa mientras está desactivada...
    assert "desactivada" in (await call(registry, "ver_recuerdos")).summary
    # ...pero la fila sigue existiendo de verdad en la base de datos.
    async with db.session() as session:
        assert len(await MemoryRepository(session).list_memories(ANA.user_id)) == 1
    # Al reactivarla, vuelve a verse sin haberse perdido.
    await call(registry, "ajustar_memoria", activar=True)
    assert (await call(registry, "ver_recuerdos")).summary["recuerdos"][0]["contenido"] == "recuerdo que se conserva"


async def test_engine_injects_active_memories_into_the_turn_context(tmp_path: Path) -> None:
    from mia.conversation import ConversationEngine, Persona  # noqa: PLC0415
    from mia.llm.fake import FakeLLMProvider, final_answer  # noqa: PLC0415

    db = await fresh_database(tmp_path, "engine_mem.db")
    async with db.session() as session:
        await MemoryRepository(session).set_enabled(ANA.user_id, True)
        await MemoryRepository(session).add_memory(ANA.user_id, "que prefiero los informes en PDF")

    llm = FakeLLMProvider(lambda req: final_answer("ok", "vale", "sonriendo"))
    engine = ConversationEngine(
        llm=llm, tools=ToolRegistry(), db=db, persona=Persona(), memory_settings=MemorySettings(enabled=True)
    )
    await engine.complete(message="hola", user=ANA, session_id=None)
    assert "que prefiero los informes en PDF" in llm.requests[-1].messages[-1].content
    await db.dispose()


async def test_engine_never_injects_memories_when_the_user_has_not_activated_it(tmp_path: Path) -> None:
    from mia.conversation import ConversationEngine, Persona  # noqa: PLC0415
    from mia.llm.fake import FakeLLMProvider, final_answer  # noqa: PLC0415

    db = await fresh_database(tmp_path, "engine_mem_off.db")
    async with db.session() as session:
        # Nunca se activó para este usuario: la fila ni siquiera llega a crearse (igual que en
        # producción), pero aunque existiera ya no debería inyectarse nada.
        await MemoryRepository(session).add_memory(ANA.user_id, "recuerdo huérfano, memoria desactivada")

    llm = FakeLLMProvider(lambda req: final_answer("ok", "vale", "sonriendo"))
    engine = ConversationEngine(
        llm=llm, tools=ToolRegistry(), db=db, persona=Persona(), memory_settings=MemorySettings(enabled=True)
    )
    await engine.complete(message="hola", user=ANA, session_id=None)
    assert "recuerdo huérfano" not in llm.requests[-1].messages[-1].content
    await db.dispose()


@pytest.fixture
def memory_settings_overrides() -> dict[str, object]:
    return {"memory": {"enabled": True}}


async def test_memory_settings_endpoint_toggles_per_user(
    tmp_path: Path, memory_settings_overrides: dict[str, object]
) -> None:
    from mia.api.services import Services  # noqa: PLC0415
    from mia.llm.fake import FakeLLMProvider  # noqa: PLC0415
    from mia.voice import CachedVoice, NullVoiceProvider  # noqa: PLC0415

    settings = make_settings(tmp_path, **memory_settings_overrides)
    db = await fresh_database(tmp_path)
    services = Services.build(settings, llm=FakeLLMProvider(), db=db, voice=CachedVoice(NullVoiceProvider()))
    app = create_app(settings, services=services)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            initial = await client.get("/api/memory/settings")
            assert initial.json() == {"available": True, "enabled": False}

            toggled = await client.put("/api/memory/settings", json={"enabled": True})
            assert toggled.json() == {"available": True, "enabled": True}

            empty = await client.get("/api/memory/items")
            assert empty.json() == {"enabled": True, "items": []}

            created = await client.put("/api/memory/settings", json={"enabled": True})
            assert created.status_code == 200
            async with db.session() as session:
                memory = await MemoryRepository(session).add_memory("dev-user", "recuerdo de prueba")
                memory_id = memory.id

            listed = await client.get("/api/memory/items")
            assert listed.json()["items"] == [
                {
                    "id": memory_id,
                    "content": "recuerdo de prueba",
                    "created_at": listed.json()["items"][0]["created_at"],
                }
            ]

            deleted = await client.delete(f"/api/memory/items/{memory_id}")
            assert deleted.json() == {"deleted": 1}
            missing = await client.delete(f"/api/memory/items/{memory_id}")
            assert missing.status_code == 404


async def test_memory_endpoints_report_unavailable_when_globally_off(tmp_path: Path) -> None:
    from mia.api.services import Services  # noqa: PLC0415
    from mia.llm.fake import FakeLLMProvider  # noqa: PLC0415
    from mia.voice import CachedVoice, NullVoiceProvider  # noqa: PLC0415

    settings = make_settings(tmp_path)  # memory.enabled=False por defecto
    db = await fresh_database(tmp_path)
    services = Services.build(settings, llm=FakeLLMProvider(), db=db, voice=CachedVoice(NullVoiceProvider()))
    app = create_app(settings, services=services)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            settings_resp = await client.get("/api/memory/settings")
            assert settings_resp.status_code == 200
            assert settings_resp.json() == {"available": False, "enabled": False}

            items_resp = await client.get("/api/memory/items")
            assert items_resp.status_code == 404

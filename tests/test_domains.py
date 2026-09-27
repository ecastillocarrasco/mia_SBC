"""Herramientas de RRHH sobre datos sintéticos, con las reglas de negocio heredadas."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from mia.auth import UserContext
from mia.conversation import ToolContext, ToolRegistry, ToolStatus
from mia.data import Base, Database
from mia.domains import build_registry
from mia.llm import ToolCall
from tests.hr_seed import TODAY, seed

NOW = datetime(TODAY.year, TODAY.month, TODAY.day, 10, 0, tzinfo=ZoneInfo("Europe/Madrid"))
ADMIN = UserContext("u", "Enrique", roles=frozenset({"mia.admin"}))


@pytest.fixture
async def registry(tmp_path: Path) -> AsyncIterator[ToolRegistry]:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'hr.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await seed(db)
    yield build_registry(db)
    await db.dispose()


async def call(registry: ToolRegistry, name: str, user: UserContext = ADMIN, **args: Any) -> Any:
    ctx = ToolContext(user=user, request_id=None, now=NOW)
    execution = await registry.execute(ToolCall("c", name, json.dumps(args)), ctx)
    return execution.result


# ------------------------------------------------------------------ personas
async def test_ambiguous_name_asks_instead_of_guessing(registry: ToolRegistry) -> None:
    result = await call(registry, "ficha_empleado", nombre="Ana")
    assert result.status is ToolStatus.AMBIGUOUS
    assert {c["nombre"] for c in result.summary["candidatos"]} == {"Ana Ruiz Sanz", "Ana Gómez"}


async def test_name_without_accents_resolves(registry: ToolRegistry) -> None:
    result = await call(registry, "ficha_empleado", nombre="ana gomez")
    assert result.status is ToolStatus.OK and result.summary["nombre"] == "Ana Gómez"


async def test_typo_suggests_close_names(registry: ToolRegistry) -> None:
    result = await call(registry, "ficha_empleado", nombre="Ana Ruis Sans")
    assert result.status is ToolStatus.NOT_FOUND
    assert result.summary["quizas_quiso_decir"] == ["Ana Ruiz Sanz"]


async def test_ficha_sets_focus_and_keeps_negative_balance(registry: ToolRegistry) -> None:
    result = await call(registry, "ficha_empleado", nombre="Ana Ruiz")
    assert result.summary["turno_hoy"]["tipo"] == "Vacaciones"
    assert result.summary["saldo_vacaciones"] == -2.5
    assert result.summary["solicitudes_pendientes"] == 1
    assert result.state_updates["foco_persona"]["empleado_id"] == 1
    assert result.presentation["type"] == "employee_card"


# ------------------------------------------------------------------ plantilla (POB-001)
async def test_headcount_is_active_by_default(registry: ToolRegistry) -> None:
    result = await call(registry, "plantilla")
    assert result.summary["total"] == 3


async def test_inactive_means_inactive(registry: ToolRegistry) -> None:
    """Fallo del sistema anterior: «inactivas» devolvía el conteo de activos."""
    result = await call(registry, "plantilla", estado="inactivos")
    assert result.summary["total"] == 1
    assert result.summary["personas"][0]["nombre"] == "Luis Gil"


async def test_department_is_matched_loosely(registry: ToolRegistry) -> None:
    result = await call(registry, "plantilla", departamento="cocina", estado="todos")
    assert result.summary["total"] == 2 and result.summary["departamento"] == "Cocina"
    assert result.state_updates == {"foco_departamento": "Cocina"}


async def test_unknown_department_lists_options(registry: ToolRegistry) -> None:
    result = await call(registry, "plantilla", departamento="Astronáutica")
    assert result.status is ToolStatus.NOT_FOUND
    assert "Pisos" in result.summary["departamentos"]


# ------------------------------------------------------------------ turnos
async def test_person_week_marks_unpublished_days(registry: ToolRegistry) -> None:
    result = await call(registry, "turnos_persona", empleado_id=4)
    kinds = [d["tipo"] for d in result.summary["dias"]]
    assert kinds == ["Baja/IT", "Baja/IT"]  # Eva: de baja hoy y mañana; el resto, sin publicar
    assert len(result.summary["dias_sin_turno_publicado"]) == 5


async def test_department_day_groups_people(registry: ToolRegistry) -> None:
    result = await call(registry, "turnos_departamento", departamento="cocina")
    assert result.summary["recuento_por_tipo"] == {"Trabajo": 1}


async def test_absences_are_merged_into_periods(registry: ToolRegistry) -> None:
    result = await call(registry, "ausencias", desde="2026-08-01", hasta="2026-08-31")
    periods = {(p["persona"], p["tipo"], p["desde"], p["hasta"]) for p in result.summary["periodos"]}
    assert ("Ana Ruiz Sanz", "Vacaciones", "2026-08-03", "2026-08-07") in periods
    assert ("Eva Sol", "Baja/IT", "2026-08-05", "2026-08-06") in periods


# ------------------------------------------------------------------ vacaciones
async def test_vacations_default_to_accepted(registry: ToolRegistry) -> None:
    result = await call(registry, "vacaciones", empleado_id=1, desde="2026-08-01", hasta="2026-09-30")
    assert result.summary["total"] == 1
    pending = await call(
        registry, "vacaciones", empleado_id=1, estado="pendientes", desde="2026-08-01", hasta="2026-09-30"
    )
    assert pending.summary["solicitudes"][0]["desde"] == "14/09/2026"


async def test_negative_balances_are_reported_as_negative(registry: ToolRegistry) -> None:
    """VAC-002."""
    result = await call(registry, "saldo_vacaciones", solo_negativos=True)
    assert result.summary["con_saldo_negativo"] == 1
    assert result.summary["saldos"][0]["saldo_actual"] == -2.5


async def test_return_is_first_published_work_shift(registry: ToolRegistry) -> None:
    """VAC-001: vuelve el lunes 10 (tras el fin de semana de descanso), no el sábado 8."""
    result = await call(registry, "reincorporacion", empleado_id=1)
    assert result.summary["motivo"] == "Vacaciones"
    assert result.summary["ausente_hasta"] == "2026-08-07"
    assert result.summary["reincorporacion"]["fecha"] == "2026-08-10"


async def test_return_is_not_guessed_without_published_shifts(registry: ToolRegistry) -> None:
    result = await call(registry, "reincorporacion", empleado_id=4)
    assert result.summary["motivo"] == "Baja/IT"
    assert result.summary["reincorporacion"] is None
    assert "no se puede afirmar" in result.summary["mensaje"]


# ------------------------------------------------------------------ transversal
async def test_stale_data_is_flagged(tmp_path: Path) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'stale.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await seed(db, fresh=False)
    result = await call(build_registry(db), "plantilla")
    await db.dispose()
    assert result.summary["al_dia"] is False and "empleados" in result.summary["aviso"]


async def test_tools_follow_permissions(registry: ToolRegistry) -> None:
    nobody = UserContext("x", "Invitado")
    names = [t.name for t in registry.schemas_for(nobody)]
    assert names == ["capacidades"]
    result = await call(registry, "plantilla", user=nobody)
    assert result.status is ToolStatus.PERMISSION_DENIED


async def test_focus_reaches_the_next_turn(tmp_path: Path) -> None:
    """Tras la ficha, «¿y su saldo?» llega al modelo con la persona en foco."""
    from mia.conversation import ConversationEngine  # noqa: PLC0415
    from mia.llm.base import LLMRequest  # noqa: PLC0415
    from mia.llm.fake import FakeLLMProvider, final_answer, tool_call  # noqa: PLC0415

    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'focus.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await seed(db)

    def script(req: LLMRequest) -> list[Any]:
        last = req.messages[-1]
        if last.role == "user" and "ficha" in last.content:
            return tool_call("ficha_empleado", {"nombre": "Ana Ruiz"})
        return final_answer("Hecho.", "Hecho.")

    llm = FakeLLMProvider(script)
    engine = ConversationEngine(llm=llm, tools=build_registry(db), db=db)
    first = await engine.complete(message="Enséñame la ficha de Ana Ruiz", user=ADMIN, session_id=None)
    await engine.complete(message="¿Y su saldo?", user=ADMIN, session_id=first.session_id)
    await db.dispose()
    assert "Persona: Ana Ruiz Sanz (empleado_id 1, Pisos)" in llm.requests[-1].system

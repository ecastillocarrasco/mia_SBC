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
from mia.domains import build_registry
from mia.llm import ToolCall
from tests.dbutil import fresh_database
from tests.hr_seed import TODAY, seed

NOW = datetime(TODAY.year, TODAY.month, TODAY.day, 10, 0, tzinfo=ZoneInfo("Europe/Madrid"))
ADMIN = UserContext("u", "Enrique", roles=frozenset({"mia.admin"}))


@pytest.fixture
async def registry(tmp_path: Path) -> AsyncIterator[ToolRegistry]:
    db = await fresh_database(tmp_path, "hr.db")
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
    card = result.summary
    assert card["hoy"]["turno"]["tipo"] == "Vacaciones"
    assert card["hoy"]["ausencia_en_curso"] == {
        "tipo": "Vacaciones",
        "desde": "2026-08-03",
        "dias_hasta_hoy": 3,
    }
    assert [d["tipo"] for d in card["semana_actual"]][:5] == ["Vacaciones"] * 5
    assert card["proximos_hitos"][0]["vuelve"] == "2026-08-10"
    assert card["vacaciones"]["saldo_actual"] == -2.5 and card["vacaciones"]["pendientes"] == 1
    assert set(card) >= {"ficha_laboral", "organizacion", "bajas_este_anio", "documentacion", "indicadores"}
    assert result.state_updates["foco_persona"]["empleado_id"] == 1
    assert result.presentation["type"] == "employee_360"


async def test_ficha_quality_flags_missing_department_section(registry: ToolRegistry) -> None:
    """Eva no tiene sección de departamento (Spa): la ficha lo señala sin caerse (fallo real del sistema anterior)."""
    result = await call(registry, "ficha_empleado", empleado_id=4)
    assert result.summary["calidad"] == "con_observaciones"
    assert any(a["componente"] == "organizacion" for a in result.summary["alertas_calidad"])


async def test_ficha_detalle_includes_full_history(registry: ToolRegistry) -> None:
    without = await call(registry, "ficha_empleado", empleado_id=1)
    assert "historico" not in without.summary
    with_detail = await call(registry, "ficha_empleado", empleado_id=1, detalle=True)
    historico = with_detail.summary["historico"]
    assert {"vacaciones", "bajas", "nominas", "documentos"} <= set(historico)
    assert historico["vacaciones"][0]["estado"] == "Aceptada"


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
    assert result.state_updates["foco_departamento"] == "Cocina"
    assert result.state_updates["ultima_poblacion"]["total"] == 2


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
    result = await call(registry, "turnos_dia", departamento="cocina")
    assert result.summary["contexto_del_dia"]["por_tipo"] == {"Trabajo": 1}
    assert result.summary["contexto_del_dia"]["trabajando_por_franja"] == {"mañana": 1}


async def test_whole_company_day_and_shift_band(registry: ToolRegistry) -> None:
    result = await call(registry, "turnos_dia", franja="mañana")
    assert result.summary["total_seleccionado"] == 1
    assert result.summary["personas"][0]["nombre"] == "Ana Gómez"
    evening = await call(registry, "turnos_dia", franja="noche")
    assert evening.summary["total_seleccionado"] == 0


async def test_unknown_department_is_not_reported_as_no_shifts(registry: ToolRegistry) -> None:
    """Fallo real: «departamento general» se contestaba como «no hay turnos publicados hoy»."""
    result = await call(registry, "turnos_dia", departamento="general")
    assert result.status is ToolStatus.NOT_FOUND
    assert "No es que no haya turnos" in result.summary["mensaje"]
    assert "Cocina" in result.summary["departamentos"]


async def test_absence_reports_real_start_not_query_start(registry: ToolRegistry) -> None:
    """AUS-001. Fallo real: «todas las bajas empezaron hoy» al consultar solo hoy."""
    result = await call(registry, "ausencias")  # solo hoy, 5 de agosto
    ana = next(p for p in result.summary["periodos"] if p["persona"] == "Ana Ruiz Sanz")
    assert (ana["desde"], ana["dias_totales_publicados"], ana["en_curso"]) == ("2026-08-03", 5, True)
    assert ana["dias_hasta_hoy"] == 3  # del lunes 3 al miércoles 5: lleva 3 días, no 5
    assert ana["vuelve"]["fecha"] == "2026-08-10"


async def test_person_absence_history_defaults_to_the_year(registry: ToolRegistry) -> None:
    result = await call(registry, "ausencias", empleado_id=4, tipos=["Baja/IT"])
    assert result.summary["desde"] == "2026-01-01"
    # Días acumulados hasta hoy (1: hoy); el periodo completo publicado dura 2.
    assert result.summary["resumen_por_tipo"]["Baja/IT"] == {"personas": 1, "periodos": 1, "dias": 1, "duracion_media_dias": 1.0}
    assert result.summary["periodos"][0]["dias_totales_publicados"] == 2
    assert result.state_updates["foco_persona"]["empleado_id"] == 4


async def test_reincorporations_list(registry: ToolRegistry) -> None:
    only_eva = await call(registry, "reincorporaciones", empleado_ids=[4])
    assert only_eva.summary["con_reincorporacion_publicada"] == 0
    result = await call(registry, "reincorporaciones")
    assert result.summary["personas_con_mas_de_un_motivo"] == []
    assert result.summary["con_reincorporacion_publicada"] == 1
    assert result.summary["reincorporaciones"][0]["persona"] == "Ana Ruiz Sanz"
    assert result.summary["ausencia_termina_pero_sin_turno_publicado"] == 1  # Eva


async def test_absences_are_merged_into_periods(registry: ToolRegistry) -> None:
    result = await call(registry, "ausencias", desde="2026-08-01", hasta="2026-08-31")
    periods = {(p["persona"], p["tipo"], p["desde"], p["hasta"]) for p in result.summary["periodos"]}
    assert ("Ana Ruiz Sanz", "Vacaciones", "2026-08-03", "2026-08-07") in periods
    assert ("Eva Sol", "Baja/IT", "2026-08-05", "2026-08-06") in periods


# ------------------------------------------------------------------ vacaciones
async def test_vacations_default_to_accepted(registry: ToolRegistry) -> None:
    result = await call(registry, "vacaciones", empleado_id=1, desde="2026-08-01", hasta="2026-09-30")
    assert result.summary["solicitudes"] == 1 and result.summary["personas_distintas"] == 1
    pending = await call(
        registry, "vacaciones", empleado_id=1, estado="pendientes", desde="2026-08-01", hasta="2026-09-30"
    )
    assert pending.summary["detalle"][0]["desde"] == "14/09/2026"


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
    db = await fresh_database(tmp_path, "stale.db")
    await seed(db, fresh=False)
    result = await call(build_registry(db), "plantilla")
    await db.dispose()
    assert result.summary["al_dia"] is False and "empleados" in result.summary["aviso"]


async def test_tools_follow_permissions(registry: ToolRegistry) -> None:
    nobody = UserContext("x", "Invitado")
    names = [t.name for t in registry.schemas_for(nobody)]
    assert set(names) == {
        "capacidades",
        "operar_resultado",
        "cruzar_resultados",
    }  # solo operan sobre lo ya visto
    result = await call(registry, "plantilla", user=nobody)
    assert result.status is ToolStatus.PERMISSION_DENIED


async def test_focus_reaches_the_next_turn(tmp_path: Path) -> None:
    """Tras la ficha, «¿y su saldo?» llega al modelo con la persona en foco."""
    from mia.conversation import ConversationEngine  # noqa: PLC0415
    from mia.llm.base import LLMRequest  # noqa: PLC0415
    from mia.llm.fake import FakeLLMProvider, final_answer, tool_call  # noqa: PLC0415

    db = await fresh_database(tmp_path, "focus.db")
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


async def test_search_with_several_matches_is_ambiguous_but_lists_them(registry: ToolRegistry) -> None:
    """Fallo real: con varias «Ana», mIA elegía una por su cuenta."""
    result = await call(registry, "buscar_empleado", nombre="Ana")
    assert result.status is ToolStatus.AMBIGUOUS
    assert len(result.summary["personas"]) == 2 and "pregúntale cuál" in result.summary["mensaje"]
    assert result.state_updates == {}


async def test_cohort_crosses_previous_result(registry: ToolRegistry) -> None:
    """CTX-002: «de esos, ¿quién tiene saldo negativo?» se calcula sobre el resultado anterior."""
    state: dict[str, Any] = {}
    ctx = ToolContext(user=ADMIN, request_id=None, now=NOW, session_state=state)
    pisos = await registry.execute(ToolCall("a", "plantilla", json.dumps({"departamento": "pisos"})), ctx)
    state.update(pisos.result.state_updates)
    crossed = await registry.execute(
        ToolCall("b", "saldo_vacaciones", json.dumps({"sobre_resultado_anterior": True})), ctx
    )
    assert [s["persona"] for s in crossed.result.summary["saldos"]] == ["Ana Ruiz Sanz"]
    without = await registry.execute(ToolCall("c", "saldo_vacaciones", json.dumps({})), ctx)
    assert without.result.summary["total_personas"] == 2


async def test_cohort_without_previous_result(registry: ToolRegistry) -> None:
    result = await call(registry, "saldo_vacaciones", sobre_resultado_anterior=True)
    assert result.status is ToolStatus.NOT_FOUND


async def test_headcount_includes_average_age(registry: ToolRegistry) -> None:
    result = await call(registry, "plantilla")
    assert result.summary["edad_media"] > 0
    assert set(result.summary["edad_media_por_departamento"]) <= {"Pisos", "Cocina", "Spa"}


async def test_department_passed_as_position_is_treated_as_department(registry: ToolRegistry) -> None:
    """Fallo real del modo sombra: «empleados de Pisos» llegó como puesto=pisos."""
    as_position = await call(registry, "plantilla", puesto="Pisos")
    as_department = await call(registry, "plantilla", departamento="Pisos")
    assert as_position.summary["total"] == as_department.summary["total"]


async def test_balances_exclude_inactive_and_sort_by_most_days(registry: ToolRegistry) -> None:
    result = await call(registry, "saldo_vacaciones", ordenar="mayor", limite=1)
    assert result.summary["saldos"][0]["saldo_actual"] == max(s["saldo_actual"] for s in result.summary["saldos"])

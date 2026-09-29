"""Herramientas de RRHH sobre datos sintéticos, con las reglas de negocio heredadas."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import date, datetime
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


async def call(
    registry: ToolRegistry, name: str, user: UserContext = ADMIN, state: dict[str, Any] | None = None, **args: Any
) -> Any:
    ctx = ToolContext(user=user, request_id=None, now=NOW, session_state=state or {})
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
    assert result.summary["resumen_por_tipo"]["Baja/IT"] == {
        "personas": 1,
        "periodos": 1,
        "dias": 1,
        "duracion_media_dias": 1.0,
        "duracion_media_completa_dias": 2.0,
    }
    assert result.summary["periodos"][0]["dias_totales_publicados"] == 2
    assert result.state_updates["foco_persona"]["empleado_id"] == 4


async def test_reincorporations_list(registry: ToolRegistry) -> None:
    only_eva = await call(registry, "reincorporaciones", empleado_ids=[4])
    assert only_eva.summary["con_reincorporacion_publicada"] == 0
    result = await call(registry, "reincorporaciones")
    assert result.summary["personas_con_mas_de_un_motivo"] == []
    assert result.summary["con_reincorporacion_publicada"] == 1
    assert result.summary["reincorporaciones"][0]["persona"] == "Ana Ruiz Sanz"
    assert result.summary["reincorporaciones"][0]["tras"] == "tras vacaciones"  # REI-001: siempre con su motivo
    assert result.summary["ausencia_termina_pero_sin_turno_publicado"] == 1  # Eva


async def test_reincorporations_include_the_four_reasons(tmp_path: Any) -> None:
    """REI-001: tras baja, permiso, vacaciones o asuntos propios, y cada una dice tras cuál vuelve."""
    from datetime import timedelta  # noqa: PLC0415

    from tests.dbutil import fresh_database  # noqa: PLC0415
    from tests.hr_seed import TODAY, _emp, _shift  # noqa: PLC0415

    db = await fresh_database(tmp_path, "rei.db")
    rows: list[Any] = []
    reasons = {"Baja/IT": "pk-1", "Permiso": "pk-2", "Vacaciones": "pk-3", "Asuntos propios": "pk-4"}
    for n, (kind, key) in enumerate(reasons.items(), 1):
        rows.append(_emp(n, f"Persona {n}", "Pisos", person_key=key))
        rows.append(_shift(1000 + n, key, f"Persona {n}", "Pisos", TODAY + timedelta(days=1), kind, kind))
        rows.append(_shift(2000 + n, key, f"Persona {n}", "Pisos", TODAY + timedelta(days=2), "Trabajo", "8:00-16:00"))
    async with db.session() as s:
        s.add_all(rows)
    result = await call(build_registry(db), "reincorporaciones")
    await db.dispose()
    assert result.summary["por_motivo"] == {k: 1 for k in reasons}
    assert {r["tras"] for r in result.summary["reincorporaciones"]} == {f"tras {k.lower()}" for k in reasons}


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
    # El foco viaja en el contexto del turno (último mensaje), no en las instrucciones fijas.
    assert "Persona: Ana Ruiz Sanz (empleado_id 1, Pisos)" in llm.requests[-1].messages[-1].content
    assert "Ana Ruiz" not in llm.requests[-1].system


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
    result = await call(registry, "plantilla", incluir_edad=True)
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


async def test_lists_are_crossed_with_the_employee_record(registry: ToolRegistry) -> None:
    """Fallo reportado: vacaciones (y otros listados) no traían el puesto de EmpleadosCorporativos."""
    vac = await call(registry, "vacaciones", desde="2026-08-01", hasta="2026-08-31")
    assert vac.presentation["columns"][:2] == ["Persona", "Puesto"]
    assert vac.presentation["rows"][0][1] == "Camarera de pisos"
    absences = await call(registry, "ausencias", desde="2026-08-01", hasta="2026-08-31")
    assert "Puesto" in absences.presentation["columns"]
    assert all(r[1] for r in absences.presentation["rows"])


async def test_cross_domain_data_over_the_previous_result(registry: ToolRegistry) -> None:
    """«De los que están de vacaciones, ¿qué puesto tienen, cuánto saldo y qué turno hoy?»."""
    ctx_state: dict[str, Any] = {}
    first = await call(registry, "vacaciones", desde="2026-08-01", hasta="2026-08-31")
    ctx_state.update(first.state_updates)
    result = await call(
        registry,
        "datos_de_personas",
        state=ctx_state,
        campos=["puesto", "saldo_vacaciones", "turno_hoy", "ultima_nomina", "nominas_no_leidas", "documentos_firmados"],
    )
    assert result.status.value == "ok"
    row = next(r for r in result.summary["detalle"] if r["persona"] == "Ana Ruiz Sanz")
    assert row["puesto"] == "Camarera de pisos"
    assert row["saldo_vacaciones"].startswith("-2.5") and row["turno_hoy"].startswith("Vacaciones")
    assert result.presentation["columns"][0] == "Persona"


async def test_group_queries_use_active_staff_unless_inactive_are_requested(tmp_path: Any) -> None:
    """POB-001: vacaciones, turnos, ausencias y reincorporaciones de grupo son de la plantilla activa."""
    from datetime import timedelta  # noqa: PLC0415

    from mia.data import Vacation  # noqa: PLC0415
    from tests.dbutil import fresh_database  # noqa: PLC0415
    from tests.hr_seed import TODAY, _emp, _shift  # noqa: PLC0415

    db = await fresh_database(tmp_path, "pob.db")
    day = TODAY + timedelta(days=1)
    async with db.session() as s:
        s.add_all(
            [
                _emp(1, "Activa Uno", "Pisos", email="a@x.test", person_key="pk-a"),
                _emp(2, "Inactiva Dos", "Pisos", active=False, email="i@x.test", person_key="pk-i"),
                _shift(1, "pk-a", "Activa Uno", "Pisos", TODAY, "Trabajo", "8:00-16:00"),
                _shift(2, "pk-i", "Inactiva Dos", "Pisos", TODAY, "Trabajo", "8:00-16:00"),
                _shift(3, "pk-a", "Activa Uno", "Pisos", TODAY, "Baja/IT", "Baja"),
                _shift(4, "pk-i", "Inactiva Dos", "Pisos", day, "Baja/IT", "Baja"),
                Vacation(
                    sp_id=1,
                    employee_email="a@x.test",
                    employee_name="Activa Uno",
                    department="Pisos",
                    department_key="pisos",
                    status="Aceptada",
                    start_date=TODAY,
                    end_date=day,
                    total_days=2,
                ),
                Vacation(
                    sp_id=2,
                    employee_email="i@x.test",
                    employee_name="Inactiva Dos",
                    department="Pisos",
                    department_key="pisos",
                    status="Aceptada",
                    start_date=TODAY,
                    end_date=day,
                    total_days=2,
                ),
            ]
        )
    registry = build_registry(db)
    args = {"desde": TODAY.isoformat(), "hasta": day.isoformat()}
    vac = await call(registry, "vacaciones", **args)
    assert vac.summary["personas_distintas"] == 1 and vac.summary["poblacion"].startswith("plantilla activa")
    assert (await call(registry, "vacaciones", incluir_inactivos=True, **args)).summary["personas_distintas"] == 2
    aus = await call(registry, "ausencias", **args)
    assert {p["persona"] for p in aus.summary["periodos"]} == {"Activa Uno"}
    assert {
        p["persona"] for p in (await call(registry, "ausencias", incluir_inactivos=True, **args)).summary["periodos"]
    } == {"Activa Uno", "Inactiva Dos"}
    day_shifts = await call(registry, "turnos_dia", fecha=TODAY.isoformat(), tipo="Trabajo")
    assert day_shifts.summary["total_seleccionado"] == 1
    assert (
        await call(registry, "turnos_dia", fecha=TODAY.isoformat(), tipo="Trabajo", incluir_inactivos=True)
    ).summary["total_seleccionado"] == 2
    # Una persona concreta se busca aunque esté inactiva.
    named = await call(registry, "ausencias", nombre="Inactiva Dos", desde=TODAY.isoformat(), hasta=day.isoformat())
    assert named.summary["periodos"][0]["persona"] == "Inactiva Dos"
    await db.dispose()


async def _absence_registry(tmp_path: Any) -> tuple[ToolRegistry, Any]:
    from tests.dbutil import fresh_database  # noqa: PLC0415
    from tests.hr_seed import _emp, _shift  # noqa: PLC0415

    db = await fresh_database(tmp_path, "aus.db")
    aug = lambda d: date(2026, 8, d)  # noqa: E731
    rows: list[Any] = [
        _emp(1, "Ana", "Pisos", person_key="pk-a"),
        _emp(2, "Beto", "Pisos", person_key="pk-b"),
        _emp(3, "Cris", "Recepción", person_key="pk-c"),
    ]
    n = 0

    def days(person: str, name: str, dept: str, first: int, last: int, kind: str) -> None:  # noqa: PLR0917
        nonlocal n
        for d in range(first, last + 1):
            n += 1
            rows.append(_shift(n, person, name, dept, aug(d), kind, kind))

    days("pk-a", "Ana", "Pisos", 3, 5, "Baja/IT")  # 3 días
    days("pk-b", "Beto", "Pisos", 10, 12, "Baja/IT")  # 3 días
    days("pk-b", "Beto", "Pisos", 13, 19, "Trabajo")
    days("pk-b", "Beto", "Pisos", 20, 21, "Baja/IT")  # 2 días (otro periodo)
    days("pk-c", "Cris", "Recepción", 1, 8, "Baja/IT")  # 8 días
    async with db.session() as s:
        s.add_all(rows)
    return build_registry(db), db


async def test_absences_are_compared_by_department_like_the_previous_system(tmp_path: Any) -> None:
    """«Compara las bajas de Pisos y Recepción en agosto»: periodos, empleados, días, media y el más largo."""
    registry, db = await _absence_registry(tmp_path)
    result = await call(registry, "ausencias", tipos=["Baja/IT"], desde="2026-08-01", hasta="2026-08-31")
    await db.dispose()
    pisos, recepcion = result.summary["por_departamento"]["Pisos"], result.summary["por_departamento"]["Recepción"]
    assert (pisos["periodos"], pisos["empleados"], pisos["dias_acumulados"]) == (3, 2, 8)
    assert pisos["duracion_media_dias"] == 2.67 and pisos["periodo_mas_largo_dias"] == 3
    assert (recepcion["periodos"], recepcion["empleados"], recepcion["dias_acumulados"]) == (1, 1, 8)
    assert recepcion["duracion_media_dias"] == 8.0 and recepcion["periodo_mas_largo_dias"] == 8


async def test_average_duration_questions_default_to_the_last_twelve_months(tmp_path: Any) -> None:
    """La media histórica del antiguo usaba 12 meses; preguntada «sin fechas» daba 1 día (el de hoy)."""
    registry, db = await _absence_registry(tmp_path)
    september = datetime(2026, 9, 1, 10, tzinfo=NOW.tzinfo)  # las bajas de agosto quedan dentro de los 12 meses
    ctx = ToolContext(
        user=ADMIN,
        request_id=None,
        now=september,
        session_state={},
        user_message="¿Cuál es la duración media de las bajas de Pisos?",
    )
    result = (
        await registry.execute(
            ToolCall("c", "ausencias", json.dumps({"tipos": ["Baja/IT"], "departamento": "Pisos"})), ctx
        )
    ).result
    await db.dispose()
    assert result.summary["desde"] == "2025-09-01" and result.summary["hasta"] == "2026-09-01"
    assert result.summary["resumen_por_tipo"]["Baja/IT"]["duracion_media_dias"] == 2.67

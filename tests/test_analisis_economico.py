"""NOM-005: análisis económico de nóminas multi-periodo (analisis_economico_nominas)."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest

from mia.auth import UserContext
from mia.connectors.sharepoint import SharePointClient, StaticTokenProvider
from mia.conversation import ToolContext, ToolRegistry, ToolStatus
from mia.data import Payslip
from mia.llm import ToolCall
from mia.modules.rrhh import build_registry
from tests.dbutil import fresh_database
from tests.hr_seed import _emp
from tests.test_domains import NOW
from tests.test_phase4b import _pdf

ADMIN = UserContext("u", "Enrique", roles=frozenset({"mia.admin"}))
MANAGER = UserContext("m", "Responsable", roles=frozenset({"mia.responsable"}))

# TODAY (ver tests/hr_seed.py) es 2026-08-05 → trimestre actual Q3 (jul-sep), trimestre pasado Q2 (abr-jun).
MESES = ["2026-04", "2026-05", "2026-06"]

# Cocina: 4 personas (grupo normal). Sala: 2 personas (por debajo de MIN_GROUP=3: debe ocultarse).
NET_BY_PERSON = {
    "pk-201": 1500.0,
    "pk-202": 1500.0,
    "pk-203": 1500.0,
    "pk-204": 1500.0,
    "pk-301": 2000.0,
    "pk-302": 2000.0,
}


def _payslip_text(net: float) -> str:
    gross = round(net + 330.15, 2)
    fmt = lambda v: f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")  # noqa: E731
    return (
        f"EMPRESA SUNSET BEACH CLUB\nMensual - Agosto 2026\n"
        "REM. TOTAL P.P. EXTRAS BASE C.C. BASE A.T. Y DES BASE I.R.P.F. T. DEVENGADO T. A DEDUCIR\n"
        f"{fmt(gross - 266.67)} 266,67 {fmt(gross)} {fmt(gross)} {fmt(gross)} {fmt(gross)} 330,15\n"
        f"Tributación I.R.P.F. (11,50 %) 214,67\n{fmt(net)} Líquido a percibir\n"
    )


def _sp_id(person_key: str, mes: str) -> int:
    person_n = int(person_key.split("-")[1])
    month_n = int(mes.split("-")[1])
    return person_n * 100 + month_n


NET_BY_SPID = {_sp_id(pk, mes): net for pk, net in NET_BY_PERSON.items() for mes in MESES}


@pytest.fixture
async def registry(tmp_path: Path) -> AsyncIterator[ToolRegistry]:
    db = await fresh_database(tmp_path, "nom_eco.db")
    async with db.session() as s:
        for n, pk in ((201, "pk-201"), (202, "pk-202"), (203, "pk-203"), (204, "pk-204")):
            s.add(_emp(n, f"Cocinero {n}", "Cocina", position="Cocinero", person_key=pk))
        for n, pk in ((301, "pk-301"), (302, "pk-302")):
            s.add(_emp(n, f"Jefe {n}", "Sala", position="Jefe de sala", person_key=pk))
        for pk in NET_BY_PERSON:
            for mes in MESES:
                year, month = (int(x) for x in mes.split("-"))
                s.add(
                    Payslip(
                        sp_id=_sp_id(pk, mes),
                        person_key=pk,
                        year=year,
                        month=month,
                        period=mes,
                        special=False,
                    )
                )

    def files(request: httpx.Request) -> httpx.Response:
        match = re.search(r"items\((\d+)\)/File", request.url.path)
        if not match:
            return httpx.Response(404)
        item = int(match.group(1))
        return httpx.Response(200, content=_pdf(_payslip_text(NET_BY_SPID[item])))

    sp = SharePointClient(
        site_url="https://x/sites/rrhh", tokens=StaticTokenProvider(), transport=httpx.MockTransport(files)
    )
    yield build_registry(db, sharepoint=sp)
    await sp.aclose()
    await db.dispose()


async def call(registry: ToolRegistry, user: UserContext = ADMIN, **args: Any) -> Any:
    ctx = ToolContext(user=user, request_id=None, now=NOW, session_state={})
    return (
        await registry.execute(ToolCall("c", "analisis_economico_nominas", json.dumps(args)), ctx)
    ).result


async def test_resolves_natural_language_quarter(registry: ToolRegistry) -> None:
    result = await call(registry, periodo="trimestre pasado")
    assert result.status is ToolStatus.OK
    assert result.summary["periodo_interpretado"] == "Q2 2026"
    assert result.summary["meses_analizados"] == MESES


async def test_unresolvable_period_is_invalid_arguments(registry: ToolRegistry) -> None:
    result = await call(registry, periodo="el otro día de la vez pasada")
    assert result.status is ToolStatus.INVALID_ARGUMENTS


async def test_totals_are_consistent_across_departments_and_months(registry: ToolRegistry) -> None:
    result = await call(registry, periodo="trimestre pasado")
    summary = result.summary
    # Sala (2 personas) está por debajo de MIN_GROUP: el total "global" expuesto es SOLO el de los
    # grupos autorizados (Cocina), nunca el de toda la empresa — si incluyera a Sala, restando el total
    # de Cocina (el único otro visible) se deduciría el importe exacto de Sala.
    assert summary["total_periodo_es_solo_grupos_autorizados"] is True
    assert summary["total_periodo"] == 4 * 1500.0 * 3  # == 18 000: solo Cocina, no 30 000 (Cocina+Sala)
    assert summary["total_por_mes"] == {m: 4 * 1500.0 for m in MESES}
    cocina = summary["por_departamento"]["Cocina"]
    assert cocina["total"] == 4 * 1500.0 * 3
    assert cocina["por_mes"] == {m: 4 * 1500.0 for m in MESES}


async def test_small_department_hides_amounts_in_summary_and_table(registry: ToolRegistry) -> None:
    """NOM-005: un departamento de 2 personas no debe exponer total ni desglose mensual (se deduciría el sueldo)."""
    result = await call(registry, periodo="trimestre pasado")
    sala = result.summary["por_departamento"]["Sala"]
    assert "total" not in sala and "por_mes" not in sala and "media" not in sala
    assert "protección de datos" in sala["importes"] or "ocultos" in sala["importes"]

    everything = json.dumps(result.summary)
    assert "4000" not in everything  # 2 * 2000: el total mensual del grupo pequeño no debe filtrarse
    assert "12000" not in everything  # 2 * 2000 * 3: ni su total trimestral

    table_view = result.presentation
    sala_row = next(row for row in table_view["rows"] if row[0] == "Sala")
    assert all(str(cell).startswith("—") for cell in sala_row[1:])


async def test_hidden_department_amount_is_not_reconstructible_by_subtraction(registry: ToolRegistry) -> None:
    """Hallazgo de la sección 6: antes, total_general - suma(departamentos visibles) reconstruía el importe
    EXACTO del grupo oculto. Con solo Cocina visible y Sala oculta, el total expuesto ya ES el de Cocina —
    no hay ningún otro número expuesto del que restar para aislar el de Sala."""
    result = await call(registry, periodo="trimestre pasado")
    summary = result.summary
    cocina_total = summary["por_departamento"]["Cocina"]["total"]
    # El total "general" expuesto coincide exactamente con el único departamento visible: no sobra ni
    # falta nada que permita, por resta, deducir el importe de Sala.
    assert summary["total_periodo"] == cocina_total


async def test_incluir_grupos_pequenos_reveals_the_small_group(registry: ToolRegistry) -> None:
    result = await call(registry, periodo="trimestre pasado", incluir_grupos_pequenos=True)
    sala = result.summary["por_departamento"]["Sala"]
    assert sala["total"] == 2 * 2000.0 * 3


async def test_charts_and_stats_are_attached_to_the_presentation(registry: ToolRegistry) -> None:
    result = await call(registry, periodo="trimestre pasado")
    view = result.presentation
    assert view["type"] == "table"
    chart_types = {c["type"] for c in view["charts"]}
    assert {"donut", "bar", "line"} <= chart_types
    assert view["stats"]["type"] == "table"
    assert any(row[0] == "Cocina" for row in view["stats"]["rows"])


async def test_single_month_also_works(registry: ToolRegistry) -> None:
    result = await call(registry, periodo="2026-05")
    assert result.status is ToolStatus.OK
    assert result.summary["meses_analizados"] == ["2026-05"]
    assert result.summary["total_periodo"] == 4 * 1500.0  # solo Cocina (visible); Sala sigue oculta


async def test_coste_empresa_never_silently_falls_back_to_devengado(registry: ToolRegistry) -> None:
    """Sección 5: si el PDF no trae cotizaciones de empresa (SS), coste_empresa NO debe rellenarse con el
    devengado bajo la misma etiqueta — son magnitudes distintas. Los payslips de prueba no incluyen esa
    sección: ninguna nómina aporta una observación de coste_empresa real (antes, el 100% se habría
    sustituido silenciosamente por el devengado)."""
    result = await call(registry, periodo="trimestre pasado", concepto="coste_empresa")
    # Sin cotizaciones SS en ningún PDF, no hay NINGUNA observación de coste_empresa real: no se inventa
    # un sustituto, así que no hay ningún departamento que mostrar (nunca "Cocina: 6000" con el devengado).
    assert result.summary["por_departamento"] == {}
    assert result.status is ToolStatus.NOT_FOUND
    advertencias = " ".join(result.summary.get("advertencias") or [])
    assert "coste_empresa" in advertencias
    assert "cotizaciones de empresa" in advertencias or "SS" in advertencias
    everything = json.dumps(result.summary)
    assert "6000" not in everything  # el devengado de Cocina (4*1500) NUNCA debe aparecer como coste_empresa


async def test_department_filter(registry: ToolRegistry) -> None:
    result = await call(registry, periodo="trimestre pasado", departamento="cocina")
    assert result.summary["personas_del_grupo"] == 4
    assert list(result.summary["por_departamento"]) == ["Cocina"]


async def test_needs_its_own_permission(registry: ToolRegistry) -> None:
    result = await call(registry, MANAGER, periodo="trimestre pasado")
    assert result.status is ToolStatus.PERMISSION_DENIED


# ======================================================================================
# Escenario Q3 2026 (julio-agosto-septiembre): importes DISTINTOS cada mes y departamento,
# para que una consulta que solo recuperase julio por error no pudiera superar estas pruebas
# «por casualidad» (todos los totales mensuales y departamentales son diferentes entre sí).
# ======================================================================================
Q3_MESES = ["2026-07", "2026-08", "2026-09"]

# Cocina (4 personas, importes DISTINTOS entre personas y meses — para probar media/mediana/min/máx de verdad)
Q3_COCINA = {
    "2026-07": {"pk-c1": 2000.0, "pk-c2": 2500.0, "pk-c3": 2500.0, "pk-c4": 3000.0},  # total 10 000
    "2026-08": {"pk-c1": 4000.0, "pk-c2": 5000.0, "pk-c3": 5000.0, "pk-c4": 6000.0},  # total 20 000
    "2026-09": {"pk-c1": 6000.0, "pk-c2": 7500.0, "pk-c3": 7500.0, "pk-c4": 9000.0},  # total 30 000
}
# Recepción (4 personas, iguales entre sí cada mes, pero con una evolución NO monótona: baja según pasan los meses)
Q3_RECEPCION = {
    "2026-07": dict.fromkeys(("pk-r1", "pk-r2", "pk-r3", "pk-r4"), 10000.0),  # total 40 000
    "2026-08": dict.fromkeys(("pk-r1", "pk-r2", "pk-r3", "pk-r4"), 3750.0),  # total 15 000
    "2026-09": dict.fromkeys(("pk-r1", "pk-r2", "pk-r3", "pk-r4"), 1250.0),  # total 5 000
}
# Sala (2 personas: por debajo de MIN_GROUP=3, debe seguir oculto en este escenario más grande)
Q3_SALA = {
    "2026-07": dict.fromkeys(("pk-s1", "pk-s2"), 1000.0),  # total 2 000
    "2026-08": dict.fromkeys(("pk-s1", "pk-s2"), 1000.0),
    "2026-09": dict.fromkeys(("pk-s1", "pk-s2"), 1000.0),
}
Q3_DEPARTMENTS = {"Cocina": Q3_COCINA, "Recepción": Q3_RECEPCION, "Sala": Q3_SALA}

# Totales esperados, calculados a mano (no reutilizan código de producción, para que la prueba sea independiente).
# Sala (2 personas) está por debajo de MIN_GROUP=3: NOM-005 exige que ni su total ni su contribución mensual
# aparezcan en ningún agregado "general" expuesto (summary, tabla, gráficos) — si Cocina y Recepción se
# muestran con su importe exacto, incluir a Sala en el total general permitiría deducirlo por resta.
Q3_DEPT_TOTAL = {"Cocina": 60000.0, "Recepción": 60000.0, "Sala": 6000.0}
Q3_MONTH_TOTAL_TRUE = {  # incluye Sala — NUNCA debe coincidir con lo que la herramienta expone
    "2026-07": 10000.0 + 40000.0 + 2000.0,  # 52 000
    "2026-08": 20000.0 + 15000.0 + 2000.0,  # 37 000
    "2026-09": 30000.0 + 5000.0 + 2000.0,  # 37 000
}
Q3_GRAND_TOTAL_TRUE = sum(Q3_DEPT_TOTAL.values())  # 126 000 — incluye Sala, no debe exponerse tal cual

# Lo que la herramienta SÍ debe exponer: solo los departamentos autorizados (Cocina + Recepción).
Q3_VISIBLE_MONTH_TOTAL = {m: Q3_MONTH_TOTAL_TRUE[m] - 2000.0 for m in Q3_MESES}
Q3_VISIBLE_TOTAL = Q3_DEPT_TOTAL["Cocina"] + Q3_DEPT_TOTAL["Recepción"]  # 120 000

# "Hoy" para estas pruebas: debe ser POSTERIOR a septiembre de 2026, o el motor de periodos recortaría el
# trimestre al considerar septiembre todavía "futuro" (igual que haría con cualquier mes que no haya llegado).
Q3_NOW = datetime(2026, 10, 10, 10, 0, tzinfo=ZoneInfo("Europe/Madrid"))


def _q3_sp_id(person_key: str, mes: str) -> int:
    # person_key tipo "pk-c1", "pk-r3", "pk-s2" -> id numérico estable y único por persona+mes
    dept_code = {"c": 1, "r": 2, "s": 3}[person_key[3]]
    person_n = int(person_key[4:])
    month_n = int(mes.split("-")[1])
    return dept_code * 10000 + person_n * 100 + month_n


Q3_NET_BY_SPID: dict[int, float] = {}
for _dept_data in Q3_DEPARTMENTS.values():
    for _mes, _people in _dept_data.items():
        for _pk, _net in _people.items():
            Q3_NET_BY_SPID[_q3_sp_id(_pk, _mes)] = _net


@pytest.fixture
async def q3_registry(tmp_path: Path) -> AsyncIterator[ToolRegistry]:
    db = await fresh_database(tmp_path, "nom_eco_q3.db")
    async with db.session() as s:
        emp_id = 1000
        for dept_name, dept_data in Q3_DEPARTMENTS.items():
            person_keys = sorted(dept_data[Q3_MESES[0]])
            position = "Cocinero" if dept_name == "Cocina" else ("Recepcionista" if dept_name == "Recepción" else "Jefe de sala")
            for pk in person_keys:
                emp_id += 1
                s.add(_emp(emp_id, f"Empleado {pk}", dept_name, position=position, person_key=pk))
            for mes, people in dept_data.items():
                year, month = (int(x) for x in mes.split("-"))
                for pk in people:
                    s.add(
                        Payslip(
                            sp_id=_q3_sp_id(pk, mes),
                            person_key=pk,
                            year=year,
                            month=month,
                            period=mes,
                            special=False,
                        )
                    )

    def files(request: httpx.Request) -> httpx.Response:
        match = re.search(r"items\((\d+)\)/File", request.url.path)
        if not match:
            return httpx.Response(404)
        item = int(match.group(1))
        return httpx.Response(200, content=_pdf(_payslip_text(Q3_NET_BY_SPID[item])))

    sp = SharePointClient(
        site_url="https://x/sites/rrhh", tokens=StaticTokenProvider(), transport=httpx.MockTransport(files)
    )
    yield build_registry(db, sharepoint=sp)
    await sp.aclose()
    await db.dispose()


async def _q3_call(registry: ToolRegistry, periodo: str) -> Any:
    ctx = ToolContext(user=ADMIN, request_id=None, now=Q3_NOW, session_state={})
    return (
        await registry.execute(
            ToolCall("c", "analisis_economico_nominas", json.dumps({"periodo": periodo})), ctx
        )
    ).result


@pytest.mark.parametrize(
    "periodo",
    ["julio a septiembre de 2026", "T3 2026", "tercer trimestre de 2026", "julio-septiembre 2026", "2026-07 a 2026-09"],
)
async def test_q3_all_natural_phrasings_produce_the_identical_quarter(q3_registry: ToolRegistry, periodo: str) -> None:
    """Las cinco formas de pedir el mismo trimestre deben producir exactamente los mismos tres meses y el mismo
    total — ninguna debe «colapsar» a julio solo."""
    result = await _q3_call(q3_registry, periodo)
    assert result.status is ToolStatus.OK, f"{periodo!r} -> {result.summary}"
    assert result.summary["meses_analizados"] == Q3_MESES, f"{periodo!r} perdió meses: {result.summary['meses_analizados']}"
    assert result.summary["total_periodo"] == Q3_VISIBLE_TOTAL


async def test_q3_month_totals_are_not_lost_or_duplicated(q3_registry: ToolRegistry) -> None:
    result = await _q3_call(q3_registry, "julio a septiembre de 2026")
    summary = result.summary
    assert summary["total_por_mes"] == Q3_VISIBLE_MONTH_TOTAL
    # Ningún mes falta y ninguno está repetido: exactamente los tres, en orden.
    assert list(summary["total_por_mes"]) == Q3_MESES


async def test_q3_department_totals_sum_to_the_grand_total(q3_registry: ToolRegistry) -> None:
    result = await _q3_call(q3_registry, "julio a septiembre de 2026")
    summary = result.summary
    cocina = summary["por_departamento"]["Cocina"]
    recepcion = summary["por_departamento"]["Recepción"]
    assert cocina["total"] == Q3_DEPT_TOTAL["Cocina"]
    assert recepcion["total"] == Q3_DEPT_TOTAL["Recepción"]
    assert cocina["por_mes"] == {"2026-07": 10000.0, "2026-08": 20000.0, "2026-09": 30000.0}
    assert recepcion["por_mes"] == {"2026-07": 40000.0, "2026-08": 15000.0, "2026-09": 5000.0}
    # Sala (grupo pequeño) sigue oculta y NO cuenta en el total general expuesto — si contara, restando
    # Cocina+Recepción (ambos visibles con su importe exacto) se deduciría el importe exacto de Sala.
    assert "total" not in summary["por_departamento"]["Sala"]
    assert summary["total_periodo_es_solo_grupos_autorizados"] is True
    visible_total = cocina["total"] + recepcion["total"]
    assert visible_total == summary["total_periodo"] == Q3_VISIBLE_TOTAL
    assert summary["total_periodo"] != Q3_GRAND_TOTAL_TRUE  # el total real (incluido Sala) NUNCA se expone


async def test_q3_descriptive_stats_are_mathematically_correct(q3_registry: ToolRegistry) -> None:
    """Verifica media/mediana/mínimo/máximo de Cocina sobre las 12 observaciones (4 personas x 3 meses),
    calculadas a mano, para descartar que el motor use una unidad estadística equivocada (p.ej. medias de medias)."""
    result = await _q3_call(q3_registry, "julio a septiembre de 2026")
    cocina = result.summary["por_departamento"]["Cocina"]
    values = sorted(v for mes in Q3_COCINA.values() for v in mes.values())
    assert len(values) == 12
    assert cocina["total"] == sum(values) == 60000.0
    assert cocina["media"] == round(sum(values) / len(values), 2) == 5000.0
    assert cocina["mediana"] == (values[5] + values[6]) / 2 == 5000.0
    assert cocina["minimo"] == min(values) == 2000.0
    assert cocina["maximo"] == max(values) == 9000.0


async def test_q3_covers_all_departments_not_just_one(q3_registry: ToolRegistry) -> None:
    result = await _q3_call(q3_registry, "julio a septiembre de 2026")
    assert set(result.summary["por_departamento"]) == {"Cocina", "Recepción", "Sala"}
    assert result.summary["personas_del_grupo"] == 4 + 4 + 2


async def test_q3_charts_reflect_all_three_months_and_departments(q3_registry: ToolRegistry) -> None:
    result = await _q3_call(q3_registry, "julio a septiembre de 2026")
    view = result.presentation
    line = next(c for c in view["charts"] if c["type"] == "line")
    assert len(line["labels"]) == 3  # tres puntos, uno por mes — no uno solo
    assert line["series"][0]["values"] == [Q3_VISIBLE_MONTH_TOTAL[m] for m in Q3_MESES]
    donut = next(c for c in view["charts"] if c["type"] == "donut")
    assert set(donut["labels"]) == {"Cocina", "Recepción"}  # Sala oculta por grupo pequeño, como en la tabla


async def test_q3_twelve_month_range_keeps_all_twelve_months(q3_registry: ToolRegistry) -> None:
    """Un rango de doce meses no debe truncarse: aquí solo hay datos sembrados en Q3, así que los otros nueve
    meses deben aparecer como «sin datos» (no desaparecer silenciosamente)."""
    result = await _q3_call(q3_registry, "octubre 2025 a septiembre 2026")
    assert result.status is ToolStatus.OK
    assert len(result.summary["meses_analizados"]) == 12
    assert result.summary["meses_con_datos"] == Q3_MESES
    assert len(result.summary["meses_sin_datos"]) == 9
    assert result.summary["total_periodo"] == Q3_VISIBLE_TOTAL  # los meses sin nómina no aportan ni restan nada


async def test_q3_real_trace_reports_no_period_range_mismatch(q3_registry: ToolRegistry) -> None:
    """Integración de extremo a extremo con el sistema de diagnóstico REAL (no eventos simulados a mano):
    envuelve la llamada real en begin_trace(), deja que la propia herramienta emita su evento de integridad
    temporal, y comprueba con el analizador real que NO marca TEMPORAL_SCOPE_MISMATCH para «T3 2026»."""
    from mia.diagnostics.analyzer import assess
    from mia.diagnostics.config import DiagnosticsSettings
    from mia.diagnostics.store import DiagnosticsStore
    from mia.diagnostics.streaming import LiveBroadcaster
    from mia.diagnostics.trace import begin_trace

    store = DiagnosticsStore(DiagnosticsSettings(enabled=True))
    broadcaster = LiveBroadcaster()
    ctx = ToolContext(user=ADMIN, request_id=None, now=Q3_NOW, session_state={})

    async with begin_trace(query="T3 2026", store=store, broadcaster=broadcaster) as trace:
        execution = await q3_registry.execute(
            ToolCall("c", "analisis_economico_nominas", json.dumps({"periodo": "T3 2026"})), ctx
        )
        trace.finish(status="completed")

    assert execution.result.status is ToolStatus.OK
    assert execution.result.summary["meses_analizados"] == Q3_MESES

    assessment = assess(trace.record)
    assert assessment["period_range_mismatch"] is False
    agg_events = [e for e in trace.record.events if e.stage == "DATA_AGGREGATION"]
    assert agg_events and agg_events[0].data["meses_resueltos"] == 3


# ======================================================================================
# Escalabilidad: antes, cualquier periodo que implicara descargar más de MAX_PEOPLE*6 (900)
# nóminas era RECHAZADO (INVALID_ARGUMENTS) sin importar que los datos existieran. Estas pruebas
# usan una plantilla sintética de cientos de personas para demostrar que ya no hay ese rechazo
# artificial. Se sustituye la descarga/parseo real de PDF por un doble determinista (monkeypatch de
# `_amounts`) para que la prueba sea rápida — la ruta de descarga+parseo real ya está cubierta por
# las pruebas Q3 de más arriba; aquí el objetivo es solo el volumen de la agregación.
# ======================================================================================
SCALE_NOW = datetime(2027, 1, 15, 10, 0, tzinfo=ZoneInfo("Europe/Madrid"))


def _even_department_sizes(n_people: int, n_depts: int) -> list[int]:
    base, extra = divmod(n_people, n_depts)
    return [base + 1 if i < extra else base for i in range(n_depts)]


NET_PER_PERSON_SCALE = 1000.0


async def _run_scale_scenario(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, name: str, n_people: int, n_depts: int, n_months: int
) -> Any:
    import mia.modules.rrhh.nominas.analisis_economico as module

    async def _fake_amounts(deps: Any, slip_id: int, gate: asyncio.Semaphore) -> dict[str, float]:
        return {"liquido": NET_PER_PERSON_SCALE, "total_devengado": NET_PER_PERSON_SCALE + 200.0}

    monkeypatch.setattr(module, "_amounts", _fake_amounts)

    meses = [f"2026-{m:02d}" for m in range(1, n_months + 1)]
    db = await fresh_database(tmp_path, name)
    sizes = _even_department_sizes(n_people, n_depts)
    sp_id = 0
    async with db.session() as s:
        person_n = 0
        for d_idx, size in enumerate(sizes):
            dept_name = f"Depto{d_idx + 1}"
            for _ in range(size):
                person_n += 1
                pk = f"pk-scale-{person_n}"
                s.add(_emp(1_000 + person_n, f"Empleado {person_n}", dept_name, position="Operario", person_key=pk))
                for mes in meses:
                    sp_id += 1
                    year, month = (int(x) for x in mes.split("-"))
                    s.add(
                        Payslip(sp_id=sp_id, person_key=pk, year=year, month=month, period=mes, special=False)
                    )

    registry = build_registry(db, sharepoint=object())
    ctx = ToolContext(user=ADMIN, request_id=None, now=SCALE_NOW, session_state={})
    periodo = "enero 2026" if n_months == 1 else f"enero-{'marzo' if n_months == 3 else 'junio' if n_months == 6 else 'diciembre'} 2026"
    execution = await registry.execute(
        ToolCall("c", "analisis_economico_nominas", json.dumps({"periodo": periodo})), ctx
    )
    await db.dispose()
    return execution.result, n_people, n_depts, n_months, sizes


@pytest.mark.parametrize("n_months", [1, 3, 6, 12])
async def test_scales_to_332_employees_without_artificial_rejection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, n_months: int
) -> None:
    result, n_people, n_depts, months, sizes = await _run_scale_scenario(
        tmp_path, monkeypatch, name=f"scale_332_{n_months}.db", n_people=332, n_depts=8, n_months=n_months
    )
    assert result.status is ToolStatus.OK, result.summary
    assert result.summary["personas_del_grupo"] == 332
    assert len(result.summary["meses_analizados"]) == n_months
    # Ningún mes perdido, ninguno duplicado, ningún departamento perdido.
    assert set(result.summary["por_departamento"]) == {f"Depto{i + 1}" for i in range(n_depts)}
    expected_total = 332 * n_months * NET_PER_PERSON_SCALE
    assert result.summary["total_periodo"] == expected_total
    for i, size in enumerate(sizes):
        dept = result.summary["por_departamento"][f"Depto{i + 1}"]
        assert dept["total"] == size * n_months * NET_PER_PERSON_SCALE
        assert dept["personas_con_nomina"] == size * n_months  # ninguna observación duplicada


async def test_scales_to_500_employees_twelve_months_without_artificial_rejection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, n_people, n_depts, months, sizes = await _run_scale_scenario(
        tmp_path, monkeypatch, name="scale_500_12.db", n_people=500, n_depts=10, n_months=12
    )
    assert result.status is ToolStatus.OK, result.summary
    assert result.summary["personas_del_grupo"] == 500
    assert len(result.summary["meses_analizados"]) == 12
    assert result.summary["total_periodo"] == 500 * 12 * NET_PER_PERSON_SCALE
    # 500 personas * 12 meses = 6000 nóminas: muy por encima del antiguo tope de 900 — antes se habría
    # rechazado con INVALID_ARGUMENTS; ahora se procesa entero.
    assert result.status is not ToolStatus.INVALID_ARGUMENTS


async def test_rectificative_payslips_are_not_double_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nóminas adicionales/rectificativas: si una persona tiene DOS filas de Payslip para el mismo mes
    (p. ej. una ordinaria y una rectificativa posterior), el agregador debe contar una sola vez, no sumar
    ambas (ya lo hacía `slip_index`, que se queda con la primera; esto lo deja probado explícitamente)."""
    import mia.modules.rrhh.nominas.analisis_economico as module

    async def _fake_amounts(deps: Any, slip_id: int, gate: asyncio.Semaphore) -> dict[str, float]:
        return {"liquido": NET_PER_PERSON_SCALE, "total_devengado": NET_PER_PERSON_SCALE + 200.0}

    monkeypatch.setattr(module, "_amounts", _fake_amounts)

    db = await fresh_database(tmp_path, "rectificativas.db")
    async with db.session() as s:
        for n, pk in ((1, "pk-rect-1"), (2, "pk-rect-2"), (3, "pk-rect-3")):
            s.add(_emp(900 + n, f"Empleado {n}", "Rectificaciones", position="Operario", person_key=pk))
        sp_id = 0
        for pk in ("pk-rect-1", "pk-rect-2", "pk-rect-3"):
            sp_id += 1
            s.add(Payslip(sp_id=sp_id, person_key=pk, year=2026, month=1, period="2026-01", special=False))
        # Rectificativa adicional para pk-rect-1 en el mismo mes: NO debe sumarse una segunda vez.
        sp_id += 1
        s.add(Payslip(sp_id=sp_id, person_key="pk-rect-1", year=2026, month=1, period="2026-01", special=False))

    registry = build_registry(db, sharepoint=object())
    ctx = ToolContext(user=ADMIN, request_id=None, now=SCALE_NOW, session_state={})
    execution = await registry.execute(
        ToolCall("c", "analisis_economico_nominas", json.dumps({"periodo": "enero 2026"})), ctx
    )
    await db.dispose()
    result = execution.result
    assert result.status is ToolStatus.OK
    dept = result.summary["por_departamento"]["Rectificaciones"]
    assert dept["personas_con_nomina"] == 3  # no 4: la rectificativa de pk-rect-1 no se cuenta aparte
    assert dept["total"] == 3 * NET_PER_PERSON_SCALE

"""Requisito 2 de la ronda de validación del usuario: "Refuerza el k-anonimato con pruebas de
inferencia por totales, departamentos, periodos y filtros cruzados." No se toca
``analisis_economico.py`` (ya tiene la lógica correcta, ver ``tests/test_analisis_economico.py``) — esto
amplía la COBERTURA de pruebas sobre vectores de ataque que esa suite todavía no ejercitaba, usando el
mismo escenario Q3 2026 ya definido allí (reutilizado, no duplicado) más un escenario propio para el
caso de dos grupos pequeños simultáneos."""

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
from mia.modules.registry import build_registry
from tests.dbutil import fresh_database
from tests.hr_seed import _emp
from tests.test_analisis_economico import Q3_NOW, q3_registry  # noqa: F401 — fixture y reloj reutilizados
from tests.test_phase4b import _pdf

ADMIN = UserContext("u", "Enrique", roles=frozenset({"mia.admin"}))


async def _call(registry: ToolRegistry, now: datetime = Q3_NOW, **args: Any) -> Any:
    ctx = ToolContext(user=ADMIN, request_id=None, now=now, session_state={})
    return (await registry.execute(ToolCall("c", "analisis_economico_nominas", json.dumps(args)), ctx)).result


# ------------------------------------------------------------------ 1) filtro directo al grupo oculto
async def test_filtering_directly_to_the_hidden_department_still_suppresses_amounts(q3_registry) -> None:
    """Ataque obvio: si pedir TODOS los departamentos oculta Sala (2 personas), ¿qué pasa si se filtra
    la consulta a EXACTAMENTE «Sala»? El umbral de k-anonimato depende de cuánta gente distinta tiene
    ESE departamento, no de cuántos departamentos más se muestren a la vez — debe seguir oculto."""
    result = await _call(q3_registry, periodo="julio a septiembre de 2026", departamento="sala")
    summary = result.summary
    assert list(summary["por_departamento"]) == ["Sala"]
    sala = summary["por_departamento"]["Sala"]
    assert "total" not in sala
    assert "ocultos" in sala["importes"]
    # Tampoco debe colarse por la tabla ni por el total general de esta consulta filtrada.
    assert "2000" not in json.dumps(summary) and "6000" not in json.dumps(summary)
    assert summary["total_periodo"] == 0.0 or summary.get("total_periodo_es_solo_grupos_autorizados") is True


# ------------------------------------------------------------------ 2) granularidad temporal
@pytest.mark.parametrize("mes", ["2026-07", "2026-08", "2026-09"])
async def test_single_month_queries_also_suppress_the_small_department(q3_registry, mes: str) -> None:
    """Ataque por periodos: Sala tiene 2 personas en CADA mes del trimestre (no solo en el agregado) —
    si alguien pidiera mes a mes en vez de el trimestre completo esperando que la supresión solo se
    aplicara al agregado, debe seguir oculto en cada mes individual también."""
    result = await _call(q3_registry, periodo=mes)
    assert result.status is ToolStatus.OK
    sala = result.summary["por_departamento"]["Sala"]
    assert "total" not in sala
    assert "ocultos" in sala["importes"]


# ------------------------------------------------------------------ 3) consistencia entre conceptos económicos
async def test_hidden_department_set_is_the_same_regardless_of_economic_concept(q3_registry) -> None:
    """Ataque por filtros cruzados: el umbral de k-anonimato depende de CUÁNTAS PERSONAS DISTINTAS
    tiene el grupo, no de qué magnitud económica se esté consultando — alternar liquido/devengado no
    debe abrir una rendija por la que un concepto sí oculte y el otro no."""
    liquido = await _call(q3_registry, periodo="julio a septiembre de 2026", concepto="liquido")
    devengado = await _call(q3_registry, periodo="julio a septiembre de 2026", concepto="devengado")
    assert liquido.status is ToolStatus.OK
    assert devengado.status is ToolStatus.OK
    hidden_in_liquido = {dk for dk, d in liquido.summary["por_departamento"].items() if "total" not in d}
    hidden_in_devengado = {dk for dk, d in devengado.summary["por_departamento"].items() if "total" not in d}
    assert hidden_in_liquido == hidden_in_devengado == {"Sala"}


# ------------------------------------------------------------------ 4) dos grupos pequeños a la vez
_TODAY = datetime(2026, 10, 10, 10, 0, tzinfo=ZoneInfo("Europe/Madrid"))
_MES = "2026-08"


@pytest.fixture
async def two_small_groups_registry(tmp_path: Path) -> AsyncIterator[ToolRegistry]:
    """Cocina (4 personas, visible) + Sala (2 personas) + Terraza (1 persona): DOS grupos por debajo de
    MIN_GROUP=3 a la vez, para comprobar que la supresión no depende de que solo haya un único grupo
    oculto (riesgo real de "supresión complementaria": con dos celdas ocultas en la misma fila de
    totales, ninguna de las dos debe quedar aislable combinando lo que SÍ se expone)."""
    db = await fresh_database(tmp_path, "nom_eco_two_hidden.db")
    net_by_person = {
        "pk-tc1": 1800.0,
        "pk-tc2": 1800.0,
        "pk-tc3": 1800.0,
        "pk-tc4": 1800.0,  # Cocina: 7200 total
        "pk-ts1": 900.0,
        "pk-ts2": 900.0,  # Sala: 1800 total (oculto)
        "pk-tt1": 500.0,  # Terraza: 500 total (oculto)
    }
    dept_by_person = {
        "pk-tc1": "Cocina",
        "pk-tc2": "Cocina",
        "pk-tc3": "Cocina",
        "pk-tc4": "Cocina",
        "pk-ts1": "Sala",
        "pk-ts2": "Sala",
        "pk-tt1": "Terraza",
    }
    sp_id_by_person = {pk: 500 + i for i, pk in enumerate(net_by_person)}
    async with db.session() as s:
        for pk, sp_id in sp_id_by_person.items():
            s.add(_emp(sp_id, f"Empleado {pk}", dept_by_person[pk], person_key=pk))
            year, month = (int(x) for x in _MES.split("-"))
            s.add(Payslip(sp_id=sp_id, person_key=pk, year=year, month=month, period=_MES, special=False))

    def files(request: httpx.Request) -> httpx.Response:
        match = re.search(r"items\((\d+)\)/File", request.url.path)
        if not match:
            return httpx.Response(404)
        sp_id = int(match.group(1))
        pk = next(k for k, v in sp_id_by_person.items() if v == sp_id)
        gross = net_by_person[pk] + 330.15
        fmt = lambda v: f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")  # noqa: E731
        text = (
            "EMPRESA SUNSET BEACH CLUB\nMensual - Agosto 2026\n"
            "REM. TOTAL P.P. EXTRAS BASE C.C. BASE A.T. Y DES BASE I.R.P.F. T. DEVENGADO T. A DEDUCIR\n"
            f"{fmt(gross - 266.67)} 266,67 {fmt(gross)} {fmt(gross)} {fmt(gross)} {fmt(gross)} 330,15\n"
            f"Tributación I.R.P.F. (11,50 %) 214,67\n{fmt(net_by_person[pk])} Líquido a percibir\n"
        )
        return httpx.Response(200, content=_pdf(text))

    sp = SharePointClient(
        site_url="https://x/sites/rrhh", tokens=StaticTokenProvider(), transport=httpx.MockTransport(files)
    )
    yield build_registry(db, sharepoint=sp)
    await sp.aclose()
    await db.dispose()


async def test_two_simultaneously_hidden_departments_neither_leaks_via_the_total(
    two_small_groups_registry: ToolRegistry,
) -> None:
    result = await _call(two_small_groups_registry, now=_TODAY, periodo=_MES)
    assert result.status is ToolStatus.OK
    summary = result.summary

    sala = summary["por_departamento"]["Sala"]
    terraza = summary["por_departamento"]["Terraza"]
    assert "total" not in sala and "ocultos" in sala["importes"]
    assert "total" not in terraza and "ocultos" in terraza["importes"]

    # El total expuesto es SOLO el de Cocina (único grupo autorizado): ni Sala (1800) ni Terraza (500),
    # ni su suma (2300), aparecen en ningún agregado — ni siquiera combinándolos entre sí. Se comprueba
    # sobre los valores numéricos reales del summary, no con una búsqueda de texto frágil.
    assert summary["total_periodo"] == 4 * 1800.0
    exposed_values = {summary["total_periodo"], *summary["total_por_mes"].values()}
    assert 1800.0 not in exposed_values  # total de Sala
    assert 500.0 not in exposed_values  # total de Terraza
    assert 2300.0 not in exposed_values  # Sala + Terraza combinados

    # La advertencia debe contar los DOS grupos ocultos, no solo uno.
    advertencias = " ".join(summary.get("advertencias") or [])
    assert "2 departamento" in advertencias

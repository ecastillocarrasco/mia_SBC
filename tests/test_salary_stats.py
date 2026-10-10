"""NOM-004: estadísticas salariales agregadas y sus salvaguardas."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

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


def _payslip_text(net: float) -> str:
    gross = round(net + 330.15, 2)
    fmt = lambda v: f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")  # noqa: E731
    return (
        f"EMPRESA SUNSET BEACH CLUB\nMensual - Agosto 2026\n"
        "REM. TOTAL P.P. EXTRAS BASE C.C. BASE A.T. Y DES BASE I.R.P.F. T. DEVENGADO T. A DEDUCIR\n"
        f"{fmt(gross - 266.67)} 266,67 {fmt(gross)} {fmt(gross)} {fmt(gross)} {fmt(gross)} 330,15\n"
        f"Tributación I.R.P.F. (11,50 %) 214,67\n{fmt(net)} Líquido a percibir\n"
    )


NETS = {101: 1400.0, 102: 1500.0, 103: 1600.0, 104: 1700.0, 105: 1800.0, 106: 1500.0}


@pytest.fixture
async def registry(tmp_path: Path) -> AsyncIterator[ToolRegistry]:
    db = await fresh_database(tmp_path, "sal.db")
    async with db.session() as s:
        for n in NETS:  # seis cocineros
            s.add(_emp(n, f"Cocinero {n}", "Cocina", position="Cocinero", person_key=f"pk-{n}"))
            s.add(Payslip(sp_id=n, person_key=f"pk-{n}", year=2026, month=8, period="2026-08", special=False))
        for n in (201, 202):  # solo dos jefes de sala: grupo demasiado pequeño
            s.add(_emp(n, f"Jefe {n}", "Sala", position="Jefe de sala", person_key=f"pk-{n}"))
            s.add(Payslip(sp_id=n, person_key=f"pk-{n}", year=2026, month=8, period="2026-08", special=False))

    def files(request: httpx.Request) -> httpx.Response:
        match = re.search(r"items\((\d+)\)/File", request.url.path)
        if not match:
            return httpx.Response(404)
        item = int(match.group(1))
        return httpx.Response(200, content=_pdf(_payslip_text(NETS.get(item, 2500.0 + item))))

    sp = SharePointClient(
        site_url="https://x/sites/rrhh", tokens=StaticTokenProvider(), transport=httpx.MockTransport(files)
    )
    yield build_registry(db, sharepoint=sp)
    await sp.aclose()
    await db.dispose()


async def call(registry: ToolRegistry, user: UserContext = ADMIN, **args: Any) -> Any:
    ctx = ToolContext(user=user, request_id=None, now=NOW, session_state={})
    return (await registry.execute(ToolCall("c", "estadisticas_salariales", json.dumps(args)), ctx)).result


async def test_average_salary_of_a_position(registry: ToolRegistry) -> None:
    result = await call(registry, puesto="cocinero")
    group = result.summary["grupos"]["Total"]
    assert group["personas"] == 6 and group["nominas_leidas"] == 6
    liq = group["liquido"]
    assert liq["media"] == 1583.33 and liq["mediana"] == 1550.0
    assert liq["minimo"] == 1400.0 and liq["maximo"] == 1800.0
    assert liq["suma"] > liq["maximo"]  # suma > máximo individual implica que hay más de uno
    assert "percentil_25" in liq and "percentil_75" in liq
    assert result.summary["poblacion"].startswith("plantilla activa")


async def test_groups_smaller_than_five_show_no_amounts(registry: ToolRegistry) -> None:
    result = await call(registry, agrupar_por="puesto")
    small = result.summary["grupos"]["Jefe de sala"]
    assert "liquido" not in small and "protección de datos" in small["importes"]
    assert "liquido" in result.summary["grupos"]["Cocinero"]
    everything = json.dumps(result.summary)
    assert not any(str(v) in everything for v in ("2701", "2702", "2701.0"))  # nada de los dos jefes


async def test_never_returns_a_persons_amount_or_name(registry: ToolRegistry) -> None:
    result = await call(registry, puesto="cocinero")
    text = json.dumps(result.summary, ensure_ascii=False)
    assert "Cocinero 101" not in text and "empleado_id" not in text


async def test_needs_its_own_permission(registry: ToolRegistry) -> None:
    assert (await call(registry, MANAGER, puesto="cocinero")).status is ToolStatus.PERMISSION_DENIED


async def test_ranking_is_computed_over_the_whole_group_not_a_sample(registry: ToolRegistry) -> None:
    """Fallo real: «los 3 que más cobraron» ordenaba solo las primeras personas de la lista (por orden alfabético)."""
    ctx = ToolContext(user=ADMIN, request_id=None, now=NOW, session_state={})
    result = (
        await registry.execute(ToolCall("c", "ranking_salarial", json.dumps({"puesto": "cocinero", "cuantos": 3})), ctx)
    ).result
    top = result.summary["ranking"]
    assert [r["persona"] for r in top] == ["Cocinero 105", "Cocinero 104", "Cocinero 103"]  # 1800, 1700, 1600
    assert top[0]["importe"] == 1800.0 and result.summary["nominas_ordenadas"] == 6
    lowest = (
        await registry.execute(
            ToolCall("c", "ranking_salarial", json.dumps({"puesto": "cocinero", "cuantos": 1, "orden": "menor"})), ctx
        )
    ).result
    assert lowest.summary["ranking"][0]["persona"] == "Cocinero 101"


async def test_ranking_refuses_small_groups_and_needs_the_permission(registry: ToolRegistry) -> None:
    ctx = ToolContext(user=ADMIN, request_id=None, now=NOW, session_state={})
    small = (
        await registry.execute(ToolCall("c", "ranking_salarial", json.dumps({"puesto": "jefe de sala"})), ctx)
    ).result
    assert small.status is ToolStatus.PERMISSION_DENIED and "protección de datos" in small.summary["mensaje"]
    denied = ToolContext(user=MANAGER, request_id=None, now=NOW, session_state={})
    assert (
        await registry.execute(ToolCall("c", "ranking_salarial", json.dumps({"puesto": "cocinero"})), denied)
    ).result.status is ToolStatus.PERMISSION_DENIED

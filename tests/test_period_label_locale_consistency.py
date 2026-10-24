"""Incidencia real (trace mia-20261012-115403-bad97707): `generar_informe` rechazaba ("invalid_
arguments") una petición de exportación legítima porque el periodo que `ReportPlanner` extrajo del
mensaje original del usuario ("agosto de 2026" → vía `_named_month()`, etiqueta "Agosto 2026") y el
periodo que `analisis_economico_nominas` había resuelto de los ARGUMENTOS del LLM ("2026-08" → vía
`_numeric_month()`, etiqueta construida con ``strftime('%B %Y')``, dependiente del locale del
servidor — "August 2026" en un proceso sin locale español) nunca coincidían como texto, aunque
representan EXACTAMENTE el mismo mes.

La guarda de coherencia temporal de Fase F (`generar()`, `src/mia/modules/rrhh/informes/tools.py`)
compara esas dos etiquetas con `normalize_key()` — cualquier inconsistencia de formato entre ramas de
`PeriodEngine.resolve()` para el MISMO mes produce un falso positivo de "periodo distinto" y bloquea
una exportación legítima."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import httpx
import pytest

from mia.auth import UserContext
from mia.conversation import ToolContext, ToolStatus
from mia.conversation.tools import remember_table
from mia.connectors.sharepoint import SharePointClient, StaticTokenProvider
from mia.data import Payslip
from mia.llm import ToolCall
from mia.modules.registry import build_registry
from mia.query.period import period_engine
from mia.text import normalize_key
from tests.conftest import make_settings
from tests.dbutil import fresh_database
from tests.hr_seed import _emp
from tests.test_phase4b import _pdf
from tests.test_report_routing_semantic_validation import _AUG_DEPARTMENTS, _payslip_text_with_ss

ADMIN = UserContext("u", "Enrique", roles=frozenset({"mia.admin"}))


@pytest.fixture
async def august_registry(tmp_path):
    """Mismo escenario sintético de agosto de 2026 (con cotizaciones SS reales) ya usado en el resto de
    esta suite — aquí solo se necesita un `ToolRegistry` directo, sin chat ni LLM."""
    db = await fresh_database(tmp_path, "period_locale.db")
    async with db.session() as s:
        sp_id = 4000
        for dept, people in _AUG_DEPARTMENTS.items():
            position = "Cocinero" if dept == "Cocina" else "Recepcionista"
            for pk in people:
                sp_id += 1
                s.add(_emp(sp_id, f"Empleado {pk}", dept, position=position, person_key=pk))
                s.add(Payslip(sp_id=sp_id, person_key=pk, year=2026, month=8, period="2026-08", special=False))

    net_by_sp_id: dict[int, float] = {}
    sp_id = 4000
    for people in _AUG_DEPARTMENTS.values():
        for net in people.values():
            sp_id += 1
            net_by_sp_id[sp_id] = net

    def files(request: httpx.Request) -> httpx.Response:
        import re  # noqa: PLC0415

        match = re.search(r"items\((\d+)\)/File", request.url.path)
        if not match:
            return httpx.Response(404)
        return httpx.Response(200, content=_pdf(_payslip_text_with_ss(net_by_sp_id[int(match.group(1))])))

    sp = SharePointClient(
        site_url="https://x/sites/rrhh", tokens=StaticTokenProvider(), transport=httpx.MockTransport(files)
    )
    settings = make_settings(tmp_path)
    registry = build_registry(db, settings.data.stale_after_minutes, settings=settings, sharepoint=sp)
    yield registry
    await sp.aclose()
    await db.dispose()


def test_numeric_and_named_month_forms_produce_the_identical_label() -> None:
    """"2026-08" (como lo normalizaría un LLM al construir argumentos de herramienta) y "agosto de
    2026" (como lo escribe el usuario) deben producir la MISMA etiqueta — nunca "August 2026" vs
    "Agosto 2026", que es exactamente lo que rompía la guarda de coherencia temporal."""
    numeric = period_engine.resolve("2026-08", today=date(2026, 10, 12))
    named = period_engine.resolve("agosto de 2026", today=date(2026, 10, 12))
    assert numeric is not None
    assert named is not None
    assert numeric.label == named.label == "Agosto 2026"
    assert normalize_key(numeric.label) == normalize_key(named.label)
    assert numeric.start == named.start
    assert numeric.end == named.end


def test_no_period_label_depends_on_the_process_locale() -> None:
    """Ninguna etiqueta debe contener nunca un nombre de mes en inglés — confirma que no queda ningún
    ``strftime('%B')`` (dependiente del locale) en ninguna rama de resolución."""
    english_months = (
        "january", "february", "march", "april", "may", "june",
        "july", "august", "september", "october", "november", "december",
    )
    today = date(2026, 10, 12)
    expressions = ["este mes", "mes pasado", "el mes pasado", "2026-01", "2026-08", "2026-12"]
    for expr in expressions:
        resolved = period_engine.resolve(expr, today=today)
        assert resolved is not None, expr
        lowered = resolved.label.lower()
        assert not any(month in lowered for month in english_months), (
            f"{expr!r} resolvió a una etiqueta dependiente del locale: {resolved.label!r}"
        )


def test_current_and_previous_month_labels_are_also_locale_independent() -> None:
    """"este mes"/"mes pasado" (las otras dos ramas que usaban ``strftime('%B %Y')``) deben seguir
    produciendo una etiqueta española reconocible, sin importar el locale del proceso."""
    today = date(2026, 8, 15)
    this_month = period_engine.resolve("este mes", today=today)
    last_month = period_engine.resolve("mes pasado", today=today)
    assert this_month is not None and this_month.label == "Agosto 2026"
    assert last_month is not None and last_month.label == "Julio 2026"


async def test_exact_trace_sequence_no_longer_rejects_the_export(august_registry) -> None:
    """Reproduce LITERALMENTE la secuencia de la traza real (round 0 → round 1, mismo turno): el LLM
    llama a `analisis_economico_nominas` con el periodo en forma numérica "2026-08" (como se vio en la
    traza real, no "agosto de 2026" en texto) y después a `generar_informe`. Antes de la corrección de
    `PeriodEngine`, esto fallaba con `invalid_arguments` por la guarda de coherencia temporal
    (etiquetas "August 2026" vs "Agosto 2026" para el mismo mes) — nunca una excepción visible, un
    rechazo silencioso de una exportación legítima."""
    ctx = ToolContext(
        user=ADMIN, request_id=None, now=datetime(2026, 10, 12, tzinfo=UTC), session_state={},
        user_message="Genera un informe completo en PDF de comparativa de costes en nóminas por departamento en agosto de 2026",
    )
    eco_execution = await august_registry.execute(
        ToolCall("call_1", "analisis_economico_nominas", json.dumps({"periodo": "2026-08", "concepto": "coste_empresa"})),
        ctx,
    )
    assert eco_execution.result.status is ToolStatus.OK
    # El ConversationEngine real hace esto tras cada ejecución (engine.py); se reproduce aquí porque
    # se llama a registry.execute() directamente, sin pasar por el motor de conversación completo.
    remember_table(
        ctx.session_state, eco_execution.result.presentation, 5000, eco_execution.result.summary,
        source_tool="analisis_economico_nominas",
    )

    informe_execution = await august_registry.execute(
        ToolCall(
            "call_2", "generar_informe",
            json.dumps({"formato": "pdf", "titulo": "Comparativa de costes en nóminas por departamento - Agosto 2026"}),
        ),
        ctx,
    )
    assert informe_execution.result.status is ToolStatus.OK, (
        f"la exportación se rechazó: {informe_execution.result.summary}"
    )

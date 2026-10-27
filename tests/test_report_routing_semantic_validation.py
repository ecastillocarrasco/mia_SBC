"""Incidencia: "Genera un informe completo de comparativa de costes en nóminas por departamento en
agosto de 2026" producía un PDF de 7 páginas con el título correcto pero contenido de la plantilla
genérica (plantilla, puestos, absentismo, vacaciones) de 'generar_informe_ejecutivo', usando además el
mes en curso (octubre) en vez de agosto — sin ningún coste salarial por departamento.

Causa raíz (confirmada leyendo el código, no supuesta):
1. `generar_informe_ejecutivo` no tiene NINGÚN dato económico (`build_executive_report()` no calcula
   coste salarial) pero su descripción ("informe... completo... por departamento... sin consultas
   previas") competía con el camino correcto de dos pasos (`analisis_economico_nominas` →
   `generar_informe`) y el LLM eligió la ruta equivocada.
2. Al no recibir fechas explícitas, el handler calculaba `desde=hoy.replace(day=1)` / `hasta=hoy` en
   silencio — de ahí los datos de octubre en vez de agosto.
3. El `ReportPlanner` (Fase B/F) ya existía, validado y con sus propias pruebas, pero nunca estaba
   conectado a ningún camino de ejecución real.

Corrección (mínima, sin tocar el motor ni el frontend 3D/HG): `generar_informe_ejecutivo` usa el
`ReportPlanner` YA EXISTENTE (no se construye otro) sobre `ctx.user_message` para detectar peticiones del
dominio económico ("payroll"). Cuando las detecta, NO se limita a rechazar con un mensaje: ejecuta de
verdad `analisis_economico_nominas` A TRAVÉS DEL MISMO `ToolRegistry` que habría usado el LLM (preservando
el permiso `NOMINAS_IMPORTES`, el trazado de diagnóstico y el timeout de esa herramienta — nunca llamando
a su handler directamente) y entrega ESE informe real, con el periodo correctamente interpretado — nunca
un error técnico ni una mera indicación de qué herramienta usar.

Nivel de prueba de cada test (requisito explícito del usuario: distinguir LLM simulado vs. flujo real):
- Sin LLM, llamada directa a `ToolRegistry.execute()` con un `ToolContext` construido a mano (no hay
  ningún modelo de por medio, ni real ni simulado): todos los tests sobre `q3_registry`, el de permisos,
  y el del `ReportPlanner` en solitario (ese ni siquiera usa un `ToolRegistry`).
- Flujo real completo con LLM SIMULADO (`FakeLLMProvider`), a través del mismo punto de entrada que usa
  el chat (`ConversationEngine.run()`, invocado también por la ruta `/api/chat`):
  `test_incident_request_through_the_real_chat_entry_point_delivers_the_real_report` — el LLM simulado
  elige la herramienta equivocada exactamente como en el incidente real; todo lo demás (routing interno,
  permisos, trazado, renderizado, persistencia) es código de producción sin ningún doble ni mock, salvo
  el propio proveedor LLM y el cliente SharePoint (sustituido por un transporte HTTP simulado con los
  datos sintéticos de esta prueba, igual que en `tests/test_analisis_economico.py`)."""

from __future__ import annotations

import io
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from openpyxl import load_workbook
from pptx import Presentation
from pypdf import PdfReader
from sqlalchemy import select

import mia.diagnostics as diagnostics_module
from mia.assets import LOGO
from mia.auth import UserContext
from mia.auth.context import ROLE_PERMISSIONS, Permission
from mia.connectors.sharepoint import SharePointClient, StaticTokenProvider
from mia.conversation import ConversationEngine, ToolContext, ToolStatus
from mia.conversation.tools import LAST_TABLE, remember_table
from mia.data import Payslip, Report
from mia.diagnostics.config import DiagnosticsSettings
from mia.diagnostics.store import DiagnosticsStore
from mia.diagnostics.streaming import LiveBroadcaster
from mia.llm import ToolCall
from mia.llm.fake import FakeLLMProvider, final_answer, tool_call
from mia.modules.registry import build_registry
from mia.modules.rrhh.informes.document import to_document
from mia.modules.rrhh.informes.render import RENDERERS
from mia.reporting.planner import planner
from tests.dbutil import fresh_database
from tests.hr_seed import _emp
from tests.test_analisis_economico import Q3_NOW, q3_registry  # noqa: F401 — fixture reutilizada
from tests.test_phase4b import _pdf

ADMIN = UserContext("u", "Enrique", roles=frozenset({"mia.admin"}))

INCIDENT_REQUEST = "Genera un informe completo de comparativa de costes en nóminas por departamento en agosto de 2026"


def _document_from(result: object) -> object:
    state: dict[str, object] = {}
    remember_table(state, result.presentation, 5000, result.summary)
    return to_document(state[LAST_TABLE])


async def test_salary_cost_request_through_executive_tool_is_redirected_to_the_real_report(
    q3_registry,
) -> None:
    """Reproduce la incidencia literal LLAMANDO A LA HERRAMIENTA QUE ELIGIÓ EL LLM EN EL INCIDENTE REAL
    ('generar_informe_ejecutivo', nunca directamente al generador económico). q3_registry no incluye
    cotizaciones de empresa (SS) en el texto de la nómina simulada, así que 'coste_empresa' (el concepto
    que infiere "costes en nóminas") no tiene observaciones reales — el resultado correcto aquí es un
    NOT_FOUND HONESTO del propio análisis económico (requisito: "si faltan datos, informa del problema"),
    nunca el contenido de la plantilla ejecutiva genérica ni un error distinto. El contenido real con
    datos sintéticos que SÍ incluyen SS se verifica en `test_incident_request_through_the_real_chat_entry_point...`."""
    ctx = ToolContext(user=ADMIN, request_id=None, now=Q3_NOW, session_state={}, user_message=INCIDENT_REQUEST)
    execution = await q3_registry.execute(
        ToolCall("c", "generar_informe_ejecutivo", json.dumps({"formato": "pdf"})), ctx
    )
    result = execution.result
    assert result.status is ToolStatus.NOT_FOUND
    # Nunca el contenido de la plantilla ejecutiva genérica (plantilla/absentismo/vacaciones).
    assert "informe" not in result.summary
    assert "secciones" not in result.summary


async def test_legitimate_executive_report_request_is_not_redirected_by_the_payroll_guard(q3_registry) -> None:
    """Control negativo: una petición de informe ejecutivo real, sin vocabulario económico, debe seguir
    funcionando exactamente igual que antes (el guard no debe producir falsos positivos)."""
    ctx = ToolContext(
        user=ADMIN,
        request_id=None,
        now=Q3_NOW,
        session_state={},
        user_message="Genera el informe ejecutivo de dirección con la plantilla y el absentismo",
    )
    execution = await q3_registry.execute(
        ToolCall("c", "generar_informe_ejecutivo", json.dumps({"formato": "pdf"})), ctx
    )
    assert execution.result.status is ToolStatus.OK


async def test_executive_report_uses_the_period_mentioned_in_the_request_instead_of_defaulting_to_today(
    q3_registry,
) -> None:
    """Sin fechas explícitas, pero con un periodo reconocible en el texto (julio de 2026), el informe
    ejecutivo debe usar julio — nunca el mes en curso (octubre, según Q3_NOW) en silencio."""
    ctx = ToolContext(
        user=ADMIN,
        request_id=None,
        now=Q3_NOW,
        session_state={},
        user_message="Necesito el informe ejecutivo de plantilla y absentismo de julio de 2026",
    )
    execution = await q3_registry.execute(
        ToolCall("c", "generar_informe_ejecutivo", json.dumps({"formato": "pdf"})), ctx
    )
    result = execution.result
    assert result.status is ToolStatus.OK
    assert result.summary["periodo"] == "2026-07-01 a 2026-07-31"


async def test_salary_cost_comparison_for_august_two_thousand_twenty_six_end_to_end_four_formats(
    q3_registry,
) -> None:
    """El camino correcto para la petición de la incidencia: `analisis_economico_nominas` con
    periodo='agosto de 2026' seguido de los 4 renderizadores — debe contener los costes reales por
    departamento de agosto, no de octubre, y conservar el branding SBC."""
    ctx = ToolContext(user=ADMIN, request_id=None, now=Q3_NOW, session_state={}, user_message=INCIDENT_REQUEST)
    execution_result = (
        await q3_registry.execute(
            # q3_registry (ver tests/test_analisis_economico.py) no incluye cotizaciones de empresa (SS)
            # en el texto de la nómina simulada, así que 'coste_empresa' no tendría observaciones; se usa
            # el concepto por defecto ('liquido'), igual que test_nominas_report_integration.py. El
            # contenido real de 'coste_empresa' con cotizaciones SS se verifica en una prueba dedicada más
            # abajo, con datos sintéticos propios.
            ToolCall("c", "analisis_economico_nominas", json.dumps({"periodo": "agosto de 2026"})),
            ctx,
        )
    ).result
    assert execution_result.status is ToolStatus.OK
    summary = execution_result.summary
    assert summary["periodo_interpretado"] == "agosto 2026" or "agosto" in summary["periodo_interpretado"].lower()
    assert summary["meses_analizados"] == ["2026-08"]
    assert {"Cocina", "Recepción"} <= set(summary["por_departamento"])
    # Sala (2 personas) sigue por debajo de MIN_GROUP=3: listada, pero sin importe real expuesto.
    assert "ocultos" in summary["por_departamento"]["Sala"]["importes"]

    doc = _document_from(execution_result)
    for fmt in ("pdf", "xlsx", "pptx", "html"):
        content = RENDERERS[fmt](doc, Q3_NOW, LOGO)
        assert content

    pdf_text = "".join(
        page.extract_text() or "" for page in PdfReader(io.BytesIO(RENDERERS["pdf"](doc, Q3_NOW, LOGO))).pages
    )
    assert "Cocina" in pdf_text
    assert "Recepción" in pdf_text

    wb = load_workbook(io.BytesIO(RENDERERS["xlsx"](doc, Q3_NOW, LOGO)))
    flat_xlsx = " ".join(
        str(c.value) for ws in wb.worksheets for row in ws.iter_rows() for c in row if c.value is not None
    )
    assert "Cocina" in flat_xlsx

    slides = Presentation(io.BytesIO(RENDERERS["pptx"](doc, Q3_NOW, LOGO))).slides
    table_parts = [
        cell.text
        for slide in slides
        for shape in slide.shapes
        if shape.has_table
        for row in shape.table.rows
        for cell in row.cells
    ]
    assert any("Cocina" in t for t in table_parts)

    html_text = RENDERERS["html"](doc, Q3_NOW, LOGO).decode("utf-8")
    assert "Cocina" in html_text


async def test_payroll_redirect_still_enforces_the_nominas_permission(q3_registry) -> None:
    """Requisito explícito del usuario ('conservando permisos'): la redirección automática ejecuta
    'analisis_economico_nominas' A TRAVÉS DEL REGISTRO, no llamando a su handler directamente — así que un
    usuario con permiso para generar informes (INFORMES_GENERAR) pero SIN permiso económico
    (NOMINAS_IMPORTES) debe seguir sin poder obtener coste salarial por esta vía indirecta."""
    original = dict(ROLE_PERMISSIONS)
    ROLE_PERMISSIONS["mia._test_informes_sin_nominas"] = frozenset({Permission.INFORMES_GENERAR})
    try:
        limited_user = UserContext("u2", "Sin nóminas", roles=frozenset({"mia._test_informes_sin_nominas"}))
        assert limited_user.has(Permission.INFORMES_GENERAR)
        assert not limited_user.has(Permission.NOMINAS_IMPORTES)
        ctx = ToolContext(
            user=limited_user, request_id=None, now=Q3_NOW, session_state={}, user_message=INCIDENT_REQUEST
        )
        execution = await q3_registry.execute(
            ToolCall("c", "generar_informe_ejecutivo", json.dumps({"formato": "pdf"})), ctx
        )
        assert execution.result.status is ToolStatus.PERMISSION_DENIED
    finally:
        ROLE_PERMISSIONS.clear()
        ROLE_PERMISSIONS.update(original)


def test_report_planner_resolves_domains_beyond_payroll() -> None:
    """Requisito 2 de la validación del usuario: comprobar que el MISMO `ReportPlanner` (no se construye
    otro) planifica correctamente Nóminas, Turnos, Vacaciones y Plantilla, no solo el caso que motivó la
    incidencia — usándolo directamente, sin pasar por 'generar_informe_ejecutivo'."""
    today = date(2026, 10, 11)
    cases = {
        "comparativa de costes en nóminas por departamento en agosto de 2026": "payroll",
        "resumen de absentismo por turnos este trimestre": "shift",
        "saldo de vacaciones del equipo": "vacation",
        "plantilla por departamento": "employee",
        # Incidencia real (variante sin "costes"/"nóminas"): "Genera importe de gastos por
        # departamento en 2026" no reconocía ningún campo económico y el guard de generar_informe
        # nunca se activaba, exportando en silencio la última tabla ajena de la sesión.
        "Genera importe de gastos por departamento en 2026": "payroll",
    }
    for text, expected_domain in cases.items():
        plan = planner.plan(text, user=ADMIN, today=today)
        domains = {m.field.domain for m in plan.metrics} | {d.domain for d in plan.dimensions}
        assert expected_domain in domains, f"{text!r} no resolvió el dominio {expected_domain!r} ({domains})"


# ────────────────────────────────────────────────────────────────── extremo a extremo real (requisito 3)

_SS_RATE = 0.30  # cotización patronal simplificada para los datos sintéticos de esta prueba


def _payslip_text_with_ss(net: float) -> str:
    """Texto de nómina sintético que SÍ incluye la sección 'APORTACIÓN EMPRESA' (a diferencia de
    `tests/test_analisis_economico.py::_payslip_text`), para que 'coste_empresa' tenga observaciones
    reales — necesario para reproducir fielmente la petición literal de la incidencia ("costes"), que
    resuelve al concepto económico más completo."""
    gross = round(net + 330.15, 2)
    ss = round(gross * _SS_RATE, 2)
    fmt = lambda v: f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")  # noqa: E731
    return (
        "EMPRESA SUNSET BEACH CLUB\nMensual - Agosto 2026\n"
        "REM. TOTAL P.P. EXTRAS BASE C.C. BASE A.T. Y DES BASE I.R.P.F. T. DEVENGADO T. A DEDUCIR\n"
        f"{fmt(gross - 266.67)} 266,67 {fmt(gross)} {fmt(gross)} {fmt(gross)} {fmt(gross)} 330,15\n"
        f"Tributación I.R.P.F. (11,50 %) 214,67\n{fmt(net)} Líquido a percibir\n"
        "APORTACIÓN EMPRESA\n"
        f"Contingencias Comunes {fmt(gross)} 23,60% {fmt(ss)}\n"
    )


_AUG_DEPARTMENTS: dict[str, dict[str, float]] = {
    "Cocina": {"pk-c1": 1500.0, "pk-c2": 1500.0, "pk-c3": 1500.0},
    "Recepción": {"pk-r1": 2000.0, "pk-r2": 2000.0, "pk-r3": 2000.0},
}


@pytest.fixture
async def incident_engine(tmp_path: Path):
    """Reconstruye, con datos sintéticos propios (con cotizaciones SS reales, a diferencia de
    `q3_registry`), exactamente el mismo cableado que usa `Services.build()` en producción
    (`build_registry()` + `ConversationEngine`) — el mismo punto de entrada que usa `/api/chat`."""
    db = await fresh_database(tmp_path, "incident_e2e.db")
    async with db.session() as s:
        sp_id = 5000
        for dept, people in _AUG_DEPARTMENTS.items():
            position = "Cocinero" if dept == "Cocina" else "Recepcionista"
            for pk in people:
                sp_id += 1
                s.add(_emp(sp_id, f"Empleado {pk}", dept, position=position, person_key=pk))
                s.add(Payslip(sp_id=sp_id, person_key=pk, year=2026, month=8, period="2026-08", special=False))

    net_by_sp_id = {}
    sp_id = 5000
    for people in _AUG_DEPARTMENTS.values():
        for net in people.values():
            sp_id += 1
            net_by_sp_id[sp_id] = net

    def files(request: httpx.Request) -> httpx.Response:
        import re  # noqa: PLC0415

        match = re.search(r"items\((\d+)\)/File", request.url.path)
        if not match:
            return httpx.Response(404)
        item = int(match.group(1))
        return httpx.Response(200, content=_pdf(_payslip_text_with_ss(net_by_sp_id[item])))

    sp = SharePointClient(
        site_url="https://x/sites/rrhh", tokens=StaticTokenProvider(), transport=httpx.MockTransport(files)
    )

    def scripted(req):
        # Reproduce el incidente real: el LLM elige PRIMERO 'generar_informe_ejecutivo' (la herramienta
        # equivocada que de verdad se seleccionó), nunca el generador económico directamente.
        if req.messages[-1].role == "tool":
            return final_answer("Aquí tienes el informe de costes salariales por departamento.", "Listo.")
        return tool_call("generar_informe_ejecutivo", {"formato": "pdf"})

    llm = FakeLLMProvider(scripted)
    settings = SimpleNamespace(
        reports=SimpleNamespace(directory=str(tmp_path / "informes"), ttl_hours=24, logo_path=None),
        data=SimpleNamespace(content_enabled=True),
    )
    registry = build_registry(db, settings=settings, llm=llm, sharepoint=sp)
    engine = ConversationEngine(llm=llm, tools=registry, db=db)
    yield engine
    await sp.aclose()
    await db.dispose()


async def test_incident_request_through_the_real_chat_entry_point_delivers_the_real_report(
    incident_engine: ConversationEngine,
) -> None:
    """Requisito 3: la solicitud EXACTA de la incidencia, desde el MISMO punto de entrada que usa el chat
    (`ConversationEngine.run()`, el método que invoca la ruta `/api/chat`), con un LLM simulado que elige
    PRIMERO la herramienta equivocada — exactamente como ocurrió en el incidente real. No se llama en
    ningún momento directamente a 'analisis_economico_nominas' ni se comprueba solo el rechazo: se
    comprueba que el usuario recibe el informe real, sin volver a pedirlo."""
    original_store, original_broadcaster = diagnostics_module._store, diagnostics_module._broadcaster
    store = DiagnosticsStore(DiagnosticsSettings(enabled=True))
    diagnostics_module.setup(store, LiveBroadcaster())
    try:
        events = [e async for e in incident_engine.run(message=INCIDENT_REQUEST, user=ADMIN, session_id=None)]
    finally:
        diagnostics_module._store, diagnostics_module._broadcaster = original_store, original_broadcaster

    # ── 1. Resultado final: el usuario recibe el informe real, no un error ni una indicación de ruta ──
    result_events = [e for e in events if e.type == "result"]
    assert result_events, "el turno no produjo ningún ResultEvent"
    turn_result = result_events[-1].result
    assert turn_result.status == "ok"
    assert turn_result.presentations and turn_result.presentations[0]["type"] == "download"

    # ── 2. Herramienta(s) realmente ejecutadas: la que eligió el LLM Y la redirección real interna ──
    trace = store.list(limit=1)[0]
    assert "generar_informe_ejecutivo" in trace.tools_called  # lo que de verdad eligió el LLM (el fallo)
    assert "analisis_economico_nominas" in trace.tools_called, (
        "el sistema debe ejecutar de verdad el análisis económico, no limitarse a la herramienta que "
        f"eligió el LLM (herramientas vistas: {trace.tools_called})"
    )

    # ── 3. Periodo interpretado, fuente consultada y agregaciones calculadas (evento emitido por la
    #      propia analisis_economico_nominas) — agosto 2026, nunca el mes en curso (octubre, Q3_NOW) ──
    aggregation_events = [e for e in trace.events if e.stage == "DATA_AGGREGATION"]
    assert aggregation_events, "no se emitió ningún evento DATA_AGGREGATION: el análisis no se ejecutó"
    agg = aggregation_events[-1].data
    assert agg["tool"] == "analisis_economico_nominas"
    # La etiqueta exacta depende del locale del sistema (p. ej. "agosto 2026" o "August 2026" vía
    # strftime) — lo que importa, independientemente del idioma, es que resuelve a agosto de 2026.
    assert "2026-08" in agg["periodo_interpretado"]
    assert agg["meses_con_datos"] == 1
    assert agg["departamentos_incluidos"] == 2  # Cocina y Recepción, ninguno oculto (3 = MIN_GROUP exacto)

    # ── 4. Documento generado y advertencias aplicadas: evento REPORT_GENERATION de la redirección real ──
    report_events = [e for e in trace.events if e.stage == "REPORT_GENERATION"]
    assert report_events, "no se emitió ningún evento REPORT_GENERATION: el documento no se generó"
    assert report_events[-1].data["tool"] == "generar_informe_ejecutivo->analisis_economico_nominas"

    # ── 5. Magnitud económica: UNA sola, explícita, nunca mezclada. "Costes en nóminas/salariales"
    #      infiere 'coste_empresa' (la más completa: devengado + cotizaciones), nunca 'devengado' ni
    #      'líquido' a la vez — la llamada interna solo pasó concepto='coste_empresa' (ver
    #      `_redirect_to_economic_analysis`/`_infer_concepto`), nunca varios conceptos en una misma tabla.
    async with incident_engine._db.session() as db:
        row = (await db.scalars(select(Report).where(Report.user_id == "u"))).first()
    assert row is not None
    pdf_bytes = Path(row.path).read_bytes()
    pdf_text = "".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf_bytes)).pages)

    # ── 6. Datos incluidos: departamentos reales de agosto, con el branding SBC — NUNCA el contenido
    #      genérico de RR.HH. (plantilla/absentismo/vacaciones/trabajo temporal) de la plantilla ejecutiva,
    #      ni una advertencia de k-anonimato que no procede aquí (3 personas = MIN_GROUP exacto). ──
    assert "Cocina" in pdf_text
    assert "Recepción" in pdf_text
    assert "Coste empresa" in pdf_text  # magnitud económica explícita en el propio documento
    assert "Gasto salarial por departamento" in pdf_text
    for generic_hr_marker in ("Absentismo ·", "Trabajo temporal ·"):
        assert generic_hr_marker not in pdf_text, (
            f"el PDF contiene {generic_hr_marker!r}: se habría colado contenido de la plantilla "
            "ejecutiva genérica en vez del informe económico real"
        )
    assert "no cumplen el mínimo" not in pdf_text  # ninguna advertencia de k-anonimato: no procede aquí
    assert LOGO.exists()

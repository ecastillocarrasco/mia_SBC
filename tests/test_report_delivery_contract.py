"""Regresiones sobre la incidencia: pedir PPTX + XLSX y no recibir ninguna descarga."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel

from mia.auth import UserContext
from mia.conversation import ConversationEngine, Persona, Tool, ToolContext, ToolRegistry, ToolResult, ToolStatus
from mia.llm.fake import FakeLLMProvider, final_answer
from mia.reporting.delivery import (
    download_formats,
    merge_report_sources,
    requested_formats,
    resolve_export_request,
)
from tests.dbutil import fresh_database

PROMPT = (
    "Analiza los turnos del 12 al 18 de octubre por departamento. "
    "Genera DOS documentos: POWERPOINT y EXCEL con logo de Sunset. "
    "Quiero ambos archivos descargables."
)


def test_detecta_ambos_formatos_y_no_acepta_solo_la_promesa_del_llm():
    assert requested_formats(PROMPT) == ("pptx", "xlsx")
    assert requested_formats("¿Conoces Excel y PowerPoint?") == ()
    assert download_formats([]) == {}


def test_detecta_word_y_html_igual_que_los_demas_formatos():
    """``_FORMAT_ORDER`` solo cubría pdf/pptx/xlsx: pedir Word o HTML a la vez que otro formato no
    activaba el contrato de entrega para esa mitad (incidencia real tras volver Word premium)."""
    assert requested_formats("Genera el informe en Word y en PDF, quiero descargarlo") == ("pdf", "docx")
    assert requested_formats("Necesito el informe en PDF y también en HTML") == ("pdf", "html")
    assert requested_formats("Quiero el documento en docx") == ("docx",)
    assert requested_formats("¿Usas Word para escribir?") == ()


def test_confirma_con_si_y_recupera_el_pedido_original():
    history = [
        SimpleNamespace(role="user", content=PROMPT),
        SimpleNamespace(role="assistant", content="¿Quieres resumen ejecutivo?"),
    ]
    assert resolve_export_request("sí", history) == (PROMPT, ("pptx", "xlsx"))
    assert resolve_export_request("sí", [SimpleNamespace(role="user", content="¿Cómo estás?")]) is None


def execution(tool: str, result_status: str, presentation: dict | None, summary=None):
    return SimpleNamespace(
        call=SimpleNamespace(name=tool),
        result=SimpleNamespace(status=SimpleNamespace(value=result_status), presentation=presentation, summary=summary),
    )


def test_descarga_requiere_resultado_ok_y_url_real_de_la_herramienta():
    good = execution(
        "generar_informe",
        "ok",
        {
            "type": "download",
            "format": "pptx",
            "url": "/api/reports/123",
        },
    )
    fake = execution(
        "generar_informe",
        "error",
        {
            "type": "download",
            "format": "xlsx",
            "url": "/api/reports/456",
        },
    )
    incorrect = execution(
        "cobertura_semanal",
        "ok",
        {
            "type": "table",
            "title": "Datos",
            "rows": [],
        },
    )
    assert download_formats([good, fake, incorrect]).keys() == {"pptx"}


def test_una_sola_llamada_con_varios_formatos_cuenta_como_entregados_todos():
    """``generar_informe`` ahora puede devolver ambos formatos pedidos en UNA sola ejecución
    (``type == "downloads"``, ver persist_document_report) en vez de una ejecución por formato —
    el contrato de entrega debe reconocer esa forma exactamente igual que la de un solo formato,
    o el motor de conversación repetiría una llamada ya satisfecha (regresión real a evitar)."""
    batched = execution(
        "generar_informe",
        "ok",
        {
            "type": "downloads",
            "title": "Costes",
            "items": [
                {"url": "/api/reports/123", "format": "pptx", "file_name": "Costes.pptx"},
                {"url": "/api/reports/456", "format": "xlsx", "file_name": "Costes.xlsx"},
            ],
        },
    )
    verified = download_formats([batched])
    assert verified.keys() == {"pptx", "xlsx"}
    assert verified["pptx"]["url"] == "/api/reports/123"
    assert verified["xlsx"]["url"] == "/api/reports/456"


def test_ocho_departamentos_no_pierden_titulo_ni_filas():
    executions = [
        execution(
            "cobertura_semanal",
            "ok",
            {
                "type": "table",
                "title": f"Departamento {i}",
                "columns": ["Departamento", "Fecha", "Trabajo"],
                "rows": [[f"Departamento {i}", f"2026-10-{day:02d}", day] for day in range(12, 19)],
            },
        )
        for i in range(8)
    ]
    merged = merge_report_sources(executions, title=PROMPT)
    assert merged["type"] == "table"
    assert len(merged["rows"]) == 56
    assert len({r[0] for r in merged["rows"]}) == 8
    assert (
        merge_report_sources(
            [
                *executions,
                execution(
                    "otra_fuente",
                    "ok",
                    {
                        "type": "table",
                        "title": "Ajena",
                        "columns": ["Departamento", "Fecha", "Trabajo"],
                        "rows": [["A", "2026-10-12", 1]],
                    },
                ),
            ],
            title=PROMPT,
        )
        is None
    )


def test_avisos_de_sincronizacion_viajan_al_informe():
    original = execution(
        "cobertura_semanal",
        "ok",
        {
            "type": "table",
            "title": "Cobertura",
            "columns": ["Departamento", "Fecha"],
            "rows": [["Cocina", "2026-10-12"]],
        },
        summary={"al_dia": False, "aviso": "Última sincronización hace 17144 minutos"},
    )
    result = merge_report_sources([original], title=PROMPT)
    assert result["__summary__"]["advertencias"] == ["Última sincronización hace 17144 minutos"]


def test_tablas_por_departamento_sin_columna_fecha_tambien_se_fusionan():
    """Incidencia real (2026-10-27): "informe comparativo de gastos en nominas... de los
    departamentos de cocina y restaurante" exportaba el PDF solo con Restaurante. La tabla de
    ``analisis_economico_nominas`` no lleva columna "Fecha" (el periodo va en la cabecera de
    columna, p. ej. "Ago 26") y cada llamada filtrada a un departamento repite el MISMO título, así
    que ni el camino de "departamento+fecha" ni el de "dashboard" (exige títulos distintos) se
    activaban -- el merge devolvía None y se exportaba solo la última llamada. Cada llamada también
    trae su propia fila "TOTAL" (el total de ESE departamento solo): debe descartarse, no fusionarse
    como si fuera un dato real, o un conflicto trivial ("TOTAL" distinto en cada llamada) abortaría
    el merge entero."""
    cocina = execution(
        "analisis_economico_nominas",
        "ok",
        {
            "type": "table",
            "title": "Gasto salarial por departamento · Agosto 2026 (Coste empresa)",
            "columns": ["Departamento", "Ago 26", "Total", "Peso %"],
            "rows": [
                ["Cocina", "68.985,59 €", "68.985,59 €", "100.0%"],
                ["TOTAL", "68.985,59 €", "68.985,59 €", "100%"],
            ],
        },
    )
    restaurante = execution(
        "analisis_economico_nominas",
        "ok",
        {
            "type": "table",
            "title": "Gasto salarial por departamento · Agosto 2026 (Coste empresa)",
            "columns": ["Departamento", "Ago 26", "Total", "Peso %"],
            "rows": [
                ["Restaurante", "114.334,10 €", "114.334,10 €", "100.0%"],
                ["TOTAL", "114.334,10 €", "114.334,10 €", "100%"],
            ],
        },
    )
    merged = merge_report_sources([cocina, restaurante], title="comparativo cocina y restaurante")
    assert merged["type"] == "table"
    assert {r[0] for r in merged["rows"]} == {"Cocina", "Restaurante"}
    assert not any(r[0].upper().startswith("TOTAL") for r in merged["rows"])


def test_una_sola_candidatura_sin_fecha_y_sin_segundo_departamento_no_fuerza_fusion():
    """Si tras descartar las filas "TOTAL" solo queda un departamento real (p. ej. dos llamadas al
    mismo departamento, o una llamada sin datos), no hay nada que fusionar -- cae al camino de
    "dashboard" existente en vez de devolver una tabla de una sola fila como si fuera comparativa."""
    only_total = execution(
        "analisis_economico_nominas",
        "ok",
        {
            "type": "table",
            "title": "Gasto salarial por departamento · Agosto 2026 (Coste empresa)",
            "columns": ["Departamento", "Ago 26", "Total", "Peso %"],
            "rows": [["TOTAL", "0,00 €", "0,00 €", "0%"]],
        },
    )
    cocina = execution(
        "analisis_economico_nominas",
        "ok",
        {
            "type": "table",
            "title": "Gasto salarial por departamento · Agosto 2026 (Coste empresa)",
            "columns": ["Departamento", "Ago 26", "Total", "Peso %"],
            "rows": [["Cocina", "68.985,59 €", "68.985,59 €", "100.0%"]],
        },
    )
    assert merge_report_sources([only_total, cocina], title="x") is None


class _NoParams(BaseModel):
    pass


class _GenerarInformeParams(BaseModel):
    formato: list[str] = []


async def _table_handler(_: _NoParams, ctx: ToolContext) -> ToolResult:
    del ctx
    return ToolResult(
        ToolStatus.OK,
        {"departamentos": [{"nombre": "Pisos", "total": 25447.35}]},
        {
            "type": "table",
            "title": "Ranking de gasto TT por departamento 2026",
            "columns": ["Departamento", "Total"],
            "rows": [["Pisos", 25447.35]],
        },
    )


async def _generar_informe_handler(p: _GenerarInformeParams, ctx: ToolContext) -> ToolResult:
    # Igual que el ``generar_informe`` real (mia.modules.rrhh.informes.tools): su propio
    # fallback a LAST_TABLE/ultima_presentacion cuando no recibe una tabla explícita.
    last = ctx.session_state.get("ultima_presentacion")
    if last is None:
        return ToolResult(ToolStatus.NOT_FOUND, "No hay ninguna tabla previa que exportar.")
    fmt = (p.formato or ["pdf"])[0]
    return ToolResult(
        ToolStatus.OK,
        {"mensaje": "Informe generado"},
        {"type": "download", "format": fmt, "url": f"/api/reports/fake-{fmt}", "file_name": f"informe.{fmt}"},
    )


async def test_pedir_el_pdf_en_un_turno_posterior_reutiliza_la_ultima_tabla(tmp_path: Path) -> None:
    """Incidencia real: tras un turno que muestra un ranking + desglose mensual (p. ej.
    "boletines_tt"), pedir "genera el informe en pdf" en el SIGUIENTE turno (sin que el LLM
    repita la llamada a la herramienta que produjo la tabla) respondía "no hay datos verificables
    y completos para exportar" aunque la tabla seguía disponible en ``session.state`` —
    ``_deliver_exports`` exigía ``message != original_request`` para reutilizar
    ``ultima_presentacion``, pero ``resolve_export_request`` devuelve el propio mensaje actual
    como ``original_request`` siempre que ese mensaje ya nombra el formato (el caso más común),
    así que esa reutilización nunca se activaba salvo en una confirmación "sí" a secas."""
    db = await fresh_database(tmp_path, "pdf_followup.db")
    registry = ToolRegistry()
    registry.register(Tool("ranking_tt", "Ranking de gasto TT.", _NoParams, _table_handler))
    registry.register(
        Tool("generar_informe", "Genera un informe descargable.", _GenerarInformeParams, _generar_informe_handler)
    )

    rounds: list[Any] = []

    def script(request: Any) -> Any:
        rounds.append(request)
        n = len(rounds)
        if n == 1:
            from mia.llm.base import LLMCompleted, ToolCall, ToolCallRequested  # noqa: PLC0415

            return [ToolCallRequested(ToolCall("c1", "ranking_tt", "{}")), LLMCompleted()]
        if n == 2:
            return final_answer("Ranking generado.", "Aquí tienes el ranking.", "sonriendo")
        # Turno siguiente: el LLM no vuelve a llamar a ninguna herramienta, confía en que el
        # backend verificará/generará el PDF a partir de lo que ya se mostró.
        return final_answer("Aquí tienes el informe.", "Aquí tienes el informe en PDF.", "entusiasmada")

    engine = ConversationEngine(llm=FakeLLMProvider(script), tools=registry, db=db, persona=Persona())
    user = UserContext("u1", "Enrique", roles=frozenset({"mia.admin"}))

    first = await engine.complete(
        message="gastos en boletines TT 2026, ranking por departamento", user=user, session_id=None
    )
    assert first.presentations[0]["type"] == "table"

    second = await engine.complete(message="quiero el pdf", user=user, session_id=first.session_id)
    assert second.status == "ok"
    assert second.presentations == [
        {"type": "download", "format": "pdf", "url": "/api/reports/fake-pdf", "file_name": "informe.pdf"}
    ]
    assert "No se han generado" not in second.answer

    await db.dispose()

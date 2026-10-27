"""Regresiones sobre la incidencia: pedir PPTX + XLSX y no recibir ninguna descarga."""
from __future__ import annotations

from types import SimpleNamespace
from mia.reporting.delivery import (
    requested_formats, resolve_export_request, download_formats, merge_report_sources,
)


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
        result=SimpleNamespace(status=SimpleNamespace(value=result_status),
                               presentation=presentation, summary=summary),
    )


def test_descarga_requiere_resultado_ok_y_url_real_de_la_herramienta():
    good = execution("generar_informe", "ok", {
        "type": "download", "format": "pptx", "url": "/api/reports/123",
    })
    fake = execution("generar_informe", "error", {
        "type": "download", "format": "xlsx", "url": "/api/reports/456",
    })
    incorrect = execution("cobertura_semanal", "ok", {
        "type": "table", "title": "Datos", "rows": [],
    })
    assert download_formats([good, fake, incorrect]).keys() == {"pptx"}


def test_una_sola_llamada_con_varios_formatos_cuenta_como_entregados_todos():
    """``generar_informe`` ahora puede devolver ambos formatos pedidos en UNA sola ejecución
    (``type == "downloads"``, ver persist_document_report) en vez de una ejecución por formato —
    el contrato de entrega debe reconocer esa forma exactamente igual que la de un solo formato,
    o el motor de conversación repetiría una llamada ya satisfecha (regresión real a evitar)."""
    batched = execution("generar_informe", "ok", {
        "type": "downloads", "title": "Costes",
        "items": [
            {"url": "/api/reports/123", "format": "pptx", "file_name": "Costes.pptx"},
            {"url": "/api/reports/456", "format": "xlsx", "file_name": "Costes.xlsx"},
        ],
    })
    verified = download_formats([batched])
    assert verified.keys() == {"pptx", "xlsx"}
    assert verified["pptx"]["url"] == "/api/reports/123"
    assert verified["xlsx"]["url"] == "/api/reports/456"


def test_ocho_departamentos_no_pierden_titulo_ni_filas():
    executions = [execution("cobertura_semanal", "ok", {
        "type": "table", "title": f"Departamento {i}",
        "columns": ["Departamento", "Fecha", "Trabajo"],
        "rows": [[f"Departamento {i}", f"2026-10-{day:02d}", day] for day in range(12, 19)],
    }) for i in range(8)]
    merged = merge_report_sources(executions, title=PROMPT)
    assert merged["type"] == "table"
    assert len(merged["rows"]) == 56
    assert len({r[0] for r in merged["rows"]}) == 8
    assert merge_report_sources(executions + [execution("otra_fuente", "ok", {
        "type": "table", "title": "Ajena", "columns": ["Departamento", "Fecha", "Trabajo"],
        "rows": [["A", "2026-10-12", 1]],
    })], title=PROMPT) is None


def test_avisos_de_sincronizacion_viajan_al_informe():
    original = execution("cobertura_semanal", "ok", {
        "type": "table", "title": "Cobertura", "columns": ["Departamento", "Fecha"],
        "rows": [["Cocina", "2026-10-12"]],
    }, summary={"al_dia": False, "aviso": "Última sincronización hace 17144 minutos"})
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
    cocina = execution("analisis_economico_nominas", "ok", {
        "type": "table", "title": "Gasto salarial por departamento · Agosto 2026 (Coste empresa)",
        "columns": ["Departamento", "Ago 26", "Total", "Peso %"],
        "rows": [["Cocina", "68.985,59 €", "68.985,59 €", "100.0%"],
                 ["TOTAL", "68.985,59 €", "68.985,59 €", "100%"]],
    })
    restaurante = execution("analisis_economico_nominas", "ok", {
        "type": "table", "title": "Gasto salarial por departamento · Agosto 2026 (Coste empresa)",
        "columns": ["Departamento", "Ago 26", "Total", "Peso %"],
        "rows": [["Restaurante", "114.334,10 €", "114.334,10 €", "100.0%"],
                 ["TOTAL", "114.334,10 €", "114.334,10 €", "100%"]],
    })
    merged = merge_report_sources([cocina, restaurante], title="comparativo cocina y restaurante")
    assert merged["type"] == "table"
    assert {r[0] for r in merged["rows"]} == {"Cocina", "Restaurante"}
    assert not any(r[0].upper().startswith("TOTAL") for r in merged["rows"])


def test_una_sola_candidatura_sin_fecha_y_sin_segundo_departamento_no_fuerza_fusion():
    """Si tras descartar las filas "TOTAL" solo queda un departamento real (p. ej. dos llamadas al
    mismo departamento, o una llamada sin datos), no hay nada que fusionar -- cae al camino de
    "dashboard" existente en vez de devolver una tabla de una sola fila como si fuera comparativa."""
    only_total = execution("analisis_economico_nominas", "ok", {
        "type": "table", "title": "Gasto salarial por departamento · Agosto 2026 (Coste empresa)",
        "columns": ["Departamento", "Ago 26", "Total", "Peso %"],
        "rows": [["TOTAL", "0,00 €", "0,00 €", "0%"]],
    })
    cocina = execution("analisis_economico_nominas", "ok", {
        "type": "table", "title": "Gasto salarial por departamento · Agosto 2026 (Coste empresa)",
        "columns": ["Departamento", "Ago 26", "Total", "Peso %"],
        "rows": [["Cocina", "68.985,59 €", "68.985,59 €", "100.0%"]],
    })
    assert merge_report_sources([only_total, cocina], title="x") is None

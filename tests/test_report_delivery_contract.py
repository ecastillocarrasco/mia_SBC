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

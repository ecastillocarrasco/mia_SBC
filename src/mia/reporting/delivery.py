"""Contrato de entrega: una promesa de informe exige artefactos reales.

No crea otro motor: solo comprueba que el motor de informes existente
produzca TODOS los formatos pedidos antes de anunciar una descarga.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

_FORMAT_ORDER = ("pdf", "pptx", "xlsx", "docx", "html")
_EXPORT_ACTION = re.compile(
    r"\b(gener\w*|crea\w*|export\w*|descarg\w*|prepar\w*|entrega\w*|"
    r"quiero|necesito|documentos?|informes?|archivos?)\b"
)
_FOLLOWUP = frozenset({"si", "vale", "adelante", "hazlo", "confirmo", "de acuerdo", "ok"})


def _normalized(value: str) -> str:
    plain = unicodedata.normalize("NFKD", value.lower())
    return "".join(c for c in plain if not unicodedata.combining(c))


def requested_formats(message: str) -> tuple[str, ...]:
    """Solo pedidos explícitos; mencionar formatos en una charla no genera documentos."""
    text = _normalized(message)
    if not _EXPORT_ACTION.search(text):
        return ()
    mentioned = {
        "pdf": bool(re.search(r"\bpdf\b", text)),
        "pptx": bool(re.search(r"\b(power\s*point|pptx?|diapositivas?)\b", text)),
        "xlsx": bool(re.search(r"\b(excel|xlsx?|hoja[s]? de calculo)\b", text)),
        "docx": bool(re.search(r"\b(word|docx?)\b", text)),
        "html": bool(re.search(r"\b(html|pagina\s*web)\b", text)),
    }
    return tuple(fmt for fmt in _FORMAT_ORDER if mentioned[fmt])


def resolve_export_request(message: str, history: list[Any]) -> tuple[str, tuple[str, ...]] | None:
    """Recupera un pedido pendiente cuando el usuario contesta 'sí' a una pregunta redundante."""
    formats = requested_formats(message)
    if formats:
        return message, formats
    if _normalized(message).strip(" .!?") not in _FOLLOWUP:
        return None
    # Evitar aplicar a un 'sí' de un tema distinto. Únicamente mirar el
    # último turno de usuario y limitarlo a la ventana de conversación inmediata.
    for turn in reversed(history[-4:]):
        if getattr(turn, "role", None) != "user":
            continue
        original = getattr(turn, "content", "")
        formats = requested_formats(original)
        return (original, formats) if formats else None
    return None


def download_formats(executions: list[Any]) -> dict[str, dict[str, Any]]:
    """Únicamente cuenta descargas verificadas devueltas por la herramienta — ya sea una sola
    ("download", una ejecución = un formato) o varias generadas en la MISMA llamada ("downloads":
    un informe pedido en varios formatos a la vez, ver ``persist_document_report``). Ambas formas se
    normalizan al mismo dict de salida para que el resto del contrato de entrega no tenga que
    distinguir el origen."""
    results = {}
    for execution in executions:
        result = execution.result
        presentation = result.presentation or {}
        if str(result.status.value) != "ok":
            continue
        if (
            presentation.get("type") == "download"
            and presentation.get("url", "").startswith("/api/reports/")
            and presentation.get("format") in _FORMAT_ORDER
        ):
            results[presentation["format"]] = presentation
        elif presentation.get("type") == "downloads":
            for item in presentation.get("items") or []:
                if (
                    isinstance(item, dict)
                    and str(item.get("url", "")).startswith("/api/reports/")
                    and item.get("format") in _FORMAT_ORDER
                ):
                    results[item["format"]] = {
                        "type": "download", "format": item["format"],
                        "url": item["url"], "file_name": item.get("file_name"),
                        "title": presentation.get("title"),
                    }
    return results


def _quality_notes(executions: list[Any]) -> dict[str, Any]:
    notes = []
    for e in executions:
        summary = getattr(e.result, "summary", None)
        if not isinstance(summary, dict):
            continue
        warnings = summary.get("advertencias") or []
        if isinstance(warnings, list):
            notes.extend(str(w) for w in warnings if isinstance(w, str) and w.strip())
        if summary.get("al_dia") is False and summary.get("aviso"):
            notes.append(str(summary["aviso"]))
    return {"advertencias": list(dict.fromkeys(notes))} if notes else {}


def merge_report_sources(executions: list[Any], *, title: str) -> dict[str, Any] | None:
    """Consolida tablas de UNA misma herramienta en un dashboard etiquetado.

    No mezcla distintos análisis: cada tabla conserva título, columnas y filas.
    Si es una única presentación, la devuelve tal cual.
    """
    sources = [e for e in executions if str(e.result.status.value) == "ok"
               and isinstance(e.result.presentation, dict)
               and e.result.presentation.get("type") in {"table", "dashboard"}]
    if len(sources) == 1:
        result = dict(sources[0].result.presentation)
        if notes := _quality_notes(sources):
            result["__summary__"] = {**(result.get("__summary__") or {}), **notes}
        return result
    if len(sources) < 2 or len({e.call.name for e in sources}) != 1:
        return None
    if not all(e.result.presentation.get("type") == "table" for e in sources):
        return None
    schemas = {tuple(map(str, e.result.presentation.get("columns") or [])) for e in sources}
    if len(schemas) != 1:
        return None
    # Si cada fila identifica inequívocamente su departamento y día,
    # podemos formar una sola tabla sin duplicar cruces de llamadas del LLM.
    columns = list(schemas.pop())
    column_names = [_normalized(c) for c in columns]
    if "departamento" in column_names and "fecha" in column_names:
        dept_idx = column_names.index("departamento")
        day_idx = column_names.index("fecha")
        dedup: dict[tuple[str, str], list[Any]] = {}
        for execution in sources:
            for row in execution.result.presentation.get("rows") or []:
                if not isinstance(row, (list, tuple)) or len(row) != len(columns):
                    return None
                key = (str(row[dept_idx]), str(row[day_idx]))
                if key in dedup and list(row) != dedup[key]:
                    return None  # Inconsistencia entre consultas; no exportar números ambiguos.
                dedup[key] = list(row)
        ordered = [dedup[key] for key in sorted(dedup)]
        result = {"type": "table", "title": title[:160],
                  "columns": columns, "rows": ordered}
        if notes := _quality_notes(sources):
            result["__summary__"] = notes
        return result
    tables = []
    for execution in sources:
        p = execution.result.presentation
        tables.append({
            "title": p.get("title") or "Resultados",
            "columns": p.get("columns", []),
            "rows": p.get("rows", []),
        })
    # Sin departamento en las filas, los títulos deben diferenciar la
    # procedencia. Ocho tablas indistinguibles NO son un desglose válido.
    if len({t["title"] for t in tables}) != len(tables):
        return None
    result = {"type": "dashboard", "title": title[:160], "kpis": {}, "tables": tables}
    if notes := _quality_notes(sources):
        result["__summary__"] = notes
    return result

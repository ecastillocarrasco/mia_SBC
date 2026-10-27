"""Composición de informes guiada por la petición dentro del motor documental EXISTENTE.

No consulta datos ni modifica importes. Pide al LLM únicamente ordenar/seleccionar
bloques ya respaldados por el backend; valida la respuesta y conserva controles de
privacidad, advertencias y metodología. Nunca es un segundo motor de informes.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from mia.llm.base import LLMProvider, LLMRequest, Message, TextDelta
from mia.llm.tiers import model_for_tier
from mia.reporting.document import Document
from mia.settings import LLMSettings, ModelTier

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "selected_indices": {"type": "array", "items": {"type": "integer"}},
        "unavailable": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["selected_indices", "unavailable"],
    "additionalProperties": False,
}

_SYSTEM = (
    "Eres editor técnico de informes corporativos. Solo seleccionas y ordenas los bloques de datos "
    "que el backend YA calculó: NO calculas cifras, NO inventas indicadores, NO añades texto ni fuentes. "
    "El usuario debe ver TODOS los conceptos que solicitó y NINGUNO de dominios ajenos a su solicitud. "
    "Recibes exclusivamente metadatos de los bloques, no las cifras. "
    "Devuelve JSON con selected_indices (índices exactos 0-based de los bloques), y unavailable "
    "(lista de requisitos expresos para los que NO hay datos identificables en esos metadatos). "
    "No declares unavailable si el bloque podría contener el dato solicitado y no puedes asegurarlo. "
    "Retén siempre las advertencias y metodología aplicables; no uses un índice que no aparezca. "
    "Si el usuario pide un informe completo sin acotar contenido, selecciona todos los bloques. "
    "Cuando haya detalle y resumen del mismo dato, mantén ambos si ayudan a validar los cálculos."
)


def _inventory(document: Document) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for idx, block in enumerate(document.blocks):
        metadata: dict[str, Any] = {"index": idx, "kind": block.kind, "title": block.title}
        if block.kind in ("table", "annex"):
            metadata["columns"] = [str(c) for c in block.data.get("columns", [])]
            metadata["rows"] = len(block.data.get("rows", []))
        elif block.kind == "kpis":
            metadata["indicators"] = list(map(str, block.data.keys()))
        elif block.kind == "chart":
            metadata["series"] = [str(s.get("name")) for s in block.data.get("series", [])]
            metadata["categories"] = len(block.data.get("labels", []))
        elif block.kind == "section":
            metadata["fields"] = list(map(str, block.data.keys()))
        result.append(metadata)
    return result


class MissingReportEvidence(Exception):
    """No puede acreditarse un requisito del usuario con los datos disponibles."""

    def __init__(self, missing: list[str]):
        self.missing = missing
        super().__init__("; ".join(missing))


async def compose_for_request(
    document: Document,
    request: str,
    llm: LLMProvider | None,
    *,
    llm_settings: LLMSettings | None = None,
) -> Document:
    """Selecciona bloques conservando sus datos originales y permisos.

    El LLM es un editor de metadatos, nunca una fuente. Una respuesta inválida
    devuelve la estructura original: no deja un documento semivacío. Para una
    petición incompleta explícita, no se fabrica el capítulo ausente.
    """
    if not request.strip() or llm is None or len(document.blocks) < 2:
        return document
    # Exportaciones/reformateos de un resultado ya validado conservan todo el contenido.
    lowered = request.casefold()
    if any(phrase in lowered for phrase in ("exporta esta", "exporta el anterior", "ahora en excel", "ahora en pdf")):
        return document
    inventory = _inventory(document)
    metadata = json.dumps(
        {"peticion": request[:1800], "titulo": document.title, "bloques": inventory},
        ensure_ascii=False,
        default=str,
    )
    model = model_for_tier(llm_settings, ModelTier.ADVANCED) if llm_settings is not None else None
    try:
        raw: list[str] = []
        async for event in llm.stream(
            LLMRequest(
                system=_SYSTEM,
                messages=[Message(role="user", content=metadata)],
                response_schema=_SCHEMA,
                max_output_tokens=750,
                model=model,
            )
        ):
            if isinstance(event, TextDelta):
                raw.append(event.text)
        decision = json.loads("".join(raw))
        if not isinstance(decision, dict):
            return document
        selected = decision.get("selected_indices")
        missing = decision.get("unavailable")
        if not isinstance(selected, list) or not selected or not isinstance(missing, list):
            return document
        if any(type(idx) is not int or idx < 0 or idx >= len(document.blocks) for idx in selected):
            return document
        if any(not isinstance(s, str) for s in missing):
            return document
        if missing:
            raise MissingReportEvidence([s[:160] for s in missing[:8] if s.strip()])
        # No podemos ocultar avisos de k-anonimato o ausencia de datos aunque la IA
        # los excluya: siempre se añaden al final si no figuran en selected_indices.
        order = list(dict.fromkeys(selected))
        for idx, block in enumerate(document.blocks):
            if block.kind in ("warnings", "methodology") and idx not in order:
                order.append(idx)
        return replace(document, blocks=[document.blocks[idx] for idx in order])
    except MissingReportEvidence:
        raise
    except Exception:
        # Degradación segura: conservamos toda la evidencia sin perder indicadores.
        return document

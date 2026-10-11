"""Narrativa generada por LLM para informes (Bloque II, Fase F: "Integración completa del LLM",
sección 3.2 de la ronda de validación del usuario: "Integra realmente narrative_guard.py. No dejes
este componente como una librería aislada sin invocación.").

Pipeline de esta pieza concreta (la Fase F completa es más grande — planificación con
``mia.reporting.planner``, autorización vía ``ToolRegistry`` ya existente — esto cubre el tramo
"evidencias → narrativa LLM → narrative guard"):

    resumen real del backend → prompt con salida estructurada → LLM (SIEMPRE a través del Privacy
    Gateway: se usa ``deps.llm``, el mismo proveedor ya envuelto que usa el resto de mIA, nunca un
    segundo camino) → afirmaciones narrativas → ``narrative_guard.enforce_narrative_integrity()`` →
    ``Block(kind="narrative")``.

Resiliente a propósito: si el LLM devuelve algo que no se puede interpretar, esta función NUNCA
rompe la generación del informe — los números y la tabla ya son correctos sin narrativa; se devuelve
`None` y el llamador simplemente no añade el bloque, en vez de fallar el informe completo por un
problema de redacción.
"""

from __future__ import annotations

import json
from typing import Any

from mia.llm.base import LLMProvider, LLMRequest, Message, TextDelta
from mia.modules.rrhh.informes.document import Block, narrative_block, narrative_statement
from mia.reporting.narrative_guard import enforce_narrative_integrity

MAX_REGENERATION_ATTEMPTS = 2
"""Sección 3.2: "permite corregir o regenerar la narrativa de manera controlada, con un número
limitado de intentos" — nunca un bucle sin fin si el LLM insiste en afirmar cifras incorrectas."""

NARRATIVE_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "statements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["fact", "interpretation", "hypothesis", "recommendation"]},
                    "text": {"type": "string", "description": "Frase en español, breve y concreta."},
                    "metric": {
                        "type": "string",
                        "description": "Para kind='fact': la clave EXACTA del resumen que respalda la afirmación.",
                    },
                    "value": {"type": "number", "description": "Para kind='fact': el valor numérico citado."},
                },
                "required": ["kind", "text"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["statements"],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = (
    "Eres el redactor de hallazgos de un informe de RRHH de Sunset Beach Club. Se te da un resumen de "
    "datos YA CALCULADOS por el backend (nunca inventes ni redondees de forma distinta a como aparecen). "
    "Escribe entre 2 y 6 afirmaciones en español. Cada una debe declarar su tipo: "
    "'fact' (hecho verificado — SIEMPRE debe citar, en 'metric', una clave EXACTA del resumen, y en "
    "'value' su valor EXACTO, sin redondear de forma distinta), 'interpretation' (lectura razonable de "
    "los hechos), 'hypothesis' (posible explicación, no confirmada) o 'recommendation' (acción sugerida). "
    "No cites como 'fact' ninguna cifra que no esté literalmente en el resumen."
)


def _flatten_numeric(data: Any, *, prefix: str = "", depth: int = 0, max_depth: int = 2) -> dict[str, float]:
    """Aplana los valores numéricos del resumen (``ToolResult.summary``) en claves con punto
    (``por_departamento.Cocina.total``), para poder comprobar cualquier "fact" que el LLM declare sin
    importar en qué nivel de anidamiento viva el dato real."""
    out: dict[str, float] = {}
    if not isinstance(data, dict) or depth > max_depth:
        return out
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            out[path] = float(value)
        elif isinstance(value, dict):
            out.update(_flatten_numeric(value, prefix=path, depth=depth + 1, max_depth=max_depth))
    return out


def _parse_statements(raw_text: str) -> list[dict[str, Any]] | None:
    try:
        payload = json.loads(raw_text)
    except (ValueError, TypeError):
        return None
    raw_statements = payload.get("statements") if isinstance(payload, dict) else None
    if not isinstance(raw_statements, list):
        return None
    out: list[dict[str, Any]] = []
    for item in raw_statements:
        if not isinstance(item, dict) or "kind" not in item or "text" not in item:
            continue
        evidence = {"metric": item["metric"], "value": item["value"]} if item.get("metric") is not None else None
        try:
            out.append(narrative_statement(item["kind"], str(item["text"]), evidence=evidence))
        except ValueError:
            # kind="fact" sin evidencia: se descarta la afirmación en vez de fallar todo el bloque —
            # ya es, en sí, justo el tipo de afirmación sin respaldo que este módulo existe para evitar.
            continue
    return out


async def _ask_llm_once(llm: LLMProvider, *, title: str, backend_values: dict[str, float]) -> list[dict[str, Any]] | None:
    user_message = (
        f"Informe: {title}\nResumen de datos (claves reales, no las inventes ni las cambies):\n"
        + json.dumps(backend_values, ensure_ascii=False)
    )
    request = LLMRequest(
        system=_SYSTEM_PROMPT,
        messages=[Message(role="user", content=user_message)],
        response_schema=NARRATIVE_RESPONSE_SCHEMA,
        max_output_tokens=600,
    )
    raw: list[str] = []
    async for event in llm.stream(request):
        if isinstance(event, TextDelta):
            raw.append(event.text)
    return _parse_statements("".join(raw))


async def generate_narrative_block(
    llm: LLMProvider | None, *, title: str, backend_summary: dict[str, Any]
) -> Block | None:
    """Genera (y verifica) un ``Block(kind="narrative")`` para un informe, o ``None`` si no hay
    proveedor LLM disponible, si no se pudo interpretar su respuesta tras los reintentos permitidos, o
    si no quedó ninguna afirmación verificable — nunca lanza una excepción que rompa la generación del
    informe en sí."""
    if llm is None:
        return None
    backend_values = _flatten_numeric(backend_summary)
    statements: list[dict[str, Any]] | None = None
    for _attempt in range(MAX_REGENERATION_ATTEMPTS):
        try:
            statements = await _ask_llm_once(llm, title=title, backend_values=backend_values)
        except Exception:  # pragma: no cover — fallo de red/proveedor: nunca rompe el informe
            statements = None
        if statements:
            break
    if not statements:
        return None
    verified = enforce_narrative_integrity(statements, backend_values=backend_values)
    return narrative_block(f"Análisis · {title}", verified)

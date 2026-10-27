"""Minimización contextual de importes económicos individuales (ajuste pedido tras la aprobación
condicionada del Bloque I, punto 1).

No se trata de anonimizar todos los números — eso degradaría cualquier análisis económico legítimo
(medias, totales, porcentajes). Se trata de detectar el patrón concreto y acotado en el que un importe
va ligado, en el MISMO registro, a una persona ya identificada (aunque esa persona esté seudonimizada
con un pseudo-token) — es decir, un dato a nivel de individuo, no un agregado. Solo en ese caso, y solo
bajo las políticas STRICT y AGGREGATED (que es, por definición, la política pensada para preferir
resultados agregados), se sustituye el importe por un marcador.

El cálculo real con el dato original siempre ya ocurrió en el backend antes de llegar aquí (p. ej.
``ranking_salarial`` ya ordenó por importe real): esto solo decide qué ve el LLM, nunca cambia el
resultado que ve el usuario final (la restauración/el documento final los genera el backend con datos
reales, nunca reconstruidos a partir de lo que diga el LLM).
"""

from __future__ import annotations

import json
import re
from typing import Any

from mia.privacy_gateway.policy_engine import Policy

_INDIVIDUAL_AMOUNT_KEYS = frozenset(
    {"importe", "liquido", "total_devengado", "coste_total_empresa", "coste_empresa_ss", "salario", "sueldo"}
)
_PERSON_KEYS = frozenset({"persona", "nombre", "empleado", "name"})
_PERSON_TOKEN_RE = re.compile(r"\[(?:PERSON|ES_\w+)_\d{3,}\]")
_REDACTED_AMOUNT = "<IMPORTE_INDIVIDUAL_PROTEGIDO>"

_CONTEXTUAL_POLICIES = frozenset({Policy.STRICT, Policy.AGGREGATED})


def _has_identified_person(obj: dict[str, Any]) -> bool:
    return any(isinstance(obj.get(key), str) and _PERSON_TOKEN_RE.search(obj[key]) for key in _PERSON_KEYS)


def _walk(obj: Any) -> Any:
    if isinstance(obj, dict):
        identified = _has_identified_person(obj)
        for key, value in obj.items():
            if identified and key in _INDIVIDUAL_AMOUNT_KEYS and isinstance(value, int | float):
                obj[key] = _REDACTED_AMOUNT
            else:
                obj[key] = _walk(value)
        return obj
    if isinstance(obj, list):
        return [_walk(item) for item in obj]
    return obj


def redact_individual_amounts(tool_result_json: str, *, policy: Policy) -> str:
    """Si ``tool_result_json`` es JSON válido (siempre lo es para un mensaje role="tool": ver
    ``ToolExecution.as_llm_output()``) y la política es STRICT o AGGREGATED, sustituye los importes
    ligados a una persona ya identificada. Si no es JSON válido, o la política no aplica, devuelve el
    texto sin tocar — nunca falla por esto (un texto que no se puede analizar como JSON simplemente no
    se minimiza más de lo que ya hace la tokenización de nombres)."""
    if policy not in _CONTEXTUAL_POLICIES:
        return tool_result_json
    try:
        parsed = json.loads(tool_result_json)
    except (ValueError, TypeError):
        return tool_result_json
    return json.dumps(_walk(parsed), ensure_ascii=False, default=str)

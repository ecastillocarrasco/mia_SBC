"""Verificación de narrativa frente a cifras del backend (Bloque II, sección 16 + requisito 7 de la
ronda de validación del usuario tras la Fase D): "verifica que las conclusiones redactadas por el LLM
coinciden con las cifras del backend. Si aparece una discrepancia, bloquea o corrige la conclusión
antes de publicarla."

Todavía no existe ningún punto de integración real donde un LLM redacte narrativa para un informe (la
Fase F del Bloque II —integración LLM— no se ha empezado en esta ronda): esto es la pieza determinista
y ya probada que esa integración futura deberá llamar antes de publicar cualquier
``Block(kind="narrative")``, siguiendo el mismo patrón que ``mia.analytics.homogeneity`` — primitivas
listas y verificadas, conectadas cuando exista el punto de ejecución real, nunca una promesa sin
código detrás.

Solo se verifican afirmaciones de tipo ``"fact"`` cuya evidencia cita una métrica conocida en
``backend_values`` — no se puede confirmar ni refutar una afirmación que no cita ningún dato
verificable, así que esas se dejan pasar sin marcar (no es lo mismo "no verificado" que "verificado y
correcto»).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_TOLERANCE_PCT = 1.0
"""Margen para diferencias de redondeo de presentación (p. ej. el LLM cita "120.000 €" de un valor real
de 119.987,43 €) — nunca para ocultar una cifra realmente distinta."""


@dataclass(frozen=True, slots=True)
class NarrativeDiscrepancy:
    statement_text: str
    metric: str
    claimed_value: float
    backend_value: float


def verify_statement(
    statement: dict[str, Any], *, backend_values: dict[str, float]
) -> NarrativeDiscrepancy | None:
    """Comprueba una única afirmación narrativa (ver ``narrative_statement()`` en ``document.py``)
    contra el valor real que su propia evidencia declara (``evidence.metric``/``evidence.value``)."""
    if statement.get("kind") != "fact":
        return None
    evidence = statement.get("evidence") or {}
    metric = evidence.get("metric")
    claimed = evidence.get("value")
    if metric is None or metric not in backend_values:
        return None
    real = backend_values[metric]
    if not isinstance(claimed, int | float) or isinstance(claimed, bool):
        return None
    if not isinstance(real, int | float) or isinstance(real, bool):
        return None
    mismatch = claimed != 0 if real == 0 else abs(claimed - real) / abs(real) * 100 > _TOLERANCE_PCT
    if not mismatch:
        return None
    return NarrativeDiscrepancy(
        statement_text=str(statement.get("text", "")), metric=metric, claimed_value=float(claimed), backend_value=float(real)
    )


def verify_narrative_block(
    statements: list[dict[str, Any]], *, backend_values: dict[str, float]
) -> list[NarrativeDiscrepancy]:
    """Todas las discrepancias reales encontradas en un bloque narrativo completo."""
    out = []
    for s in statements:
        d = verify_statement(s, backend_values=backend_values)
        if d is not None:
            out.append(d)
    return out


def enforce_narrative_integrity(
    statements: list[dict[str, Any]], *, backend_values: dict[str, float]
) -> list[dict[str, Any]]:
    """Nunca deja publicar una afirmación cuantitativa que contradiga la cifra real del backend. En vez
    de "corregir" el texto inventando qué quiso decir el LLM, lo SUSTITUYE por un aviso explícito de
    discrepancia bloqueada — con la cifra real visible, nunca oculta ni reescrita en silencio."""
    by_text = {d.statement_text: d for d in verify_narrative_block(statements, backend_values=backend_values)}
    out = []
    for s in statements:
        d = by_text.get(str(s.get("text", "")))
        if d is None:
            out.append(s)
            continue
        out.append(
            {
                **s,
                "text": (
                    f"[CONCLUSIÓN BLOQUEADA: discrepancia con el backend] El texto original afirmaba "
                    f"{d.claimed_value!r} para «{d.metric}», pero el dato real verificado es {d.backend_value!r}."
                ),
                "evidence": {**(s.get("evidence") or {}), "blocked": True, "backend_value": d.backend_value},
            }
        )
    return out

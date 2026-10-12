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

from collections.abc import Callable
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


@dataclass(frozen=True, slots=True)
class NarrativePeriodDiscrepancy:
    statement_text: str
    claimed_period: str
    expected_period: str


def verify_statement_period(statement: dict[str, Any], *, expected_period: str | None) -> NarrativePeriodDiscrepancy | None:
    """Fase F, "coherencia temporal": comprueba el periodo que una afirmación ``fact`` declara en su
    propia evidencia ESTRUCTURADA (``evidence.period`` — nunca analizando con expresiones regulares el
    periodo que la PROSA libre describe) frente al periodo real del informe (``expected_period``, p. ej.
    ``summary["periodo_interpretado"]``, ya calculado por el motor analítico).

    Si la afirmación no declara periodo, o no hay ningún ``expected_period`` con el que comparar, se
    deja pasar SIN MARCAR — no es lo mismo "no verificable" que "verificado y correcto", el mismo
    principio ya aplicado a una métrica desconocida en ``verify_statement``."""
    if statement.get("kind") != "fact" or not expected_period:
        return None
    evidence = statement.get("evidence") or {}
    claimed_period = evidence.get("period")
    if not claimed_period or not isinstance(claimed_period, str):
        return None
    from mia.text import normalize_key  # noqa: PLC0415 — evita un ciclo a nivel de módulo

    if normalize_key(claimed_period) == normalize_key(expected_period):
        return None
    return NarrativePeriodDiscrepancy(
        statement_text=str(statement.get("text", "")), claimed_period=claimed_period, expected_period=expected_period
    )


def enforce_narrative_period_coherence(
    statements: list[dict[str, Any]], *, expected_period: str | None
) -> list[dict[str, Any]]:
    """Nunca deja publicar una afirmación que atribuya su cifra a un periodo distinto del real del
    informe. Misma filosofía que ``enforce_narrative_integrity``: SUSTITUYE por un aviso explícito con
    ambos periodos visibles, nunca corrige en silencio el texto original ni asume cuál era la
    intención del LLM."""
    out = []
    for s in statements:
        d = verify_statement_period(s, expected_period=expected_period)
        if d is None:
            out.append(s)
            continue
        out.append(
            {
                **s,
                "text": (
                    f"[CONCLUSIÓN BLOQUEADA: periodo incoherente] El texto original atribuía este dato a "
                    f"«{d.claimed_period}», pero el periodo real de este informe es «{d.expected_period}»."
                ),
                "evidence": {
                    **(s.get("evidence") or {}),
                    "period_blocked": True,
                    "expected_period": d.expected_period,
                },
            }
        )
    return out


def enforce_narrative_privacy(
    statements: list[dict[str, Any]],
    *,
    pii_scan: Callable[[str], list[Any]] | None,
    authorized_subjects: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    """Fase F: "validación de narrativa mediante Privacy Gateway". ``pii_scan`` es
    ``PrivacyGateway.scan_text_for_pii`` (o ``None`` si el proveedor no lo expone, p. ej. en pruebas con
    un LLM simulado) — nunca se reimplementa la detección aquí, solo se decide qué hacer con el
    resultado.

    Tres autorizaciones DISTINTAS, que esta función NUNCA confunde entre sí:
      1. Acceso del usuario al dato — ``Permission`` en el registro de herramientas, ya resuelto antes
         de que exista ningún resumen.
      2. Inclusión en el documento final — NOM-004/NOM-005, ya resueltos dentro del motor analítico que
         calculó ``backend_summary`` (hidden groups, importes individuales nunca expuestos).
      3. Exposición al proveedor LLM / aparición en la narrativa GENERADA — lo que decide ESTA función.

    ``authorized_subjects`` es el conjunto EXPLÍCITO de sujetos que la LLAMADA concreta a
    ``generate_narrative_block`` autorizó (``authorized_subjects``) — NUNCA se infiere mirando qué
    cadenas de texto aparecen en ``backend_summary``: que el backend haya calculado o mostrado un dato
    (autorización 2) no implica que esté autorizado a exponerse al LLM o a esta narrativa (autorización
    3) — confundir ambas es precisamente lo que permitiría una fuga. Por defecto (conjunto vacío) NINGÚN
    nombre propio se considera autorizado — fail-closed, igual que el resto del Privacy Gateway.

    En vez de parchear la frase con un marcador (dejaría una prosa rota tipo "el coste de <PERSON>
    fue..."), BLOQUEA la afirmación completa cuando aparece un dato no autorizado — igual que
    ``enforce_narrative_integrity`` hace con una discrepancia numérica, nunca en silencio y nunca
    guardando el dato detectado en la evidencia."""
    if pii_scan is None:
        return statements
    out = []
    for s in statements:
        text = str(s.get("text", ""))
        entities = pii_scan(text) if text else []
        leaked = [e for e in entities if not _is_explicitly_authorized(e, text, authorized_subjects)]
        if not leaked:
            out.append(s)
            continue
        kinds = sorted({str(getattr(e, "entity_type", "DESCONOCIDO")) for e in leaked})
        out.append(
            {
                **s,
                "text": (
                    "[CONCLUSIÓN BLOQUEADA: posible dato personal detectado] Esta afirmación mencionaba "
                    f"información que parece identificar a una persona ({', '.join(kinds)}) y no se publica."
                ),
                "evidence": {**(s.get("evidence") or {}), "privacy_blocked": True, "entity_types": kinds},
            }
        )
    return out


def _is_explicitly_authorized(entity: Any, text: str, authorized_subjects: frozenset[str]) -> bool:
    """Solo compara contra la lista EXPLÍCITA que declaró quien llamó — nunca contra el resumen
    completo del backend (ver docstring de ``enforce_narrative_privacy``)."""
    start, end = getattr(entity, "start", None), getattr(entity, "end", None)
    if start is None or end is None:
        return False
    detected = text[start:end].strip().lower()
    if not detected:
        return False
    return any(detected in subject.lower() or subject.lower() in detected for subject in authorized_subjects)

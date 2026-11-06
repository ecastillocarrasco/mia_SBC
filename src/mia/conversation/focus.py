"""Mecanismo único para detectar foco conversacional obsoleto (persona, departamento, periodo…).

Cada tipo de dato se declara una sola vez como un ``FocusSlot``: cómo leer, en el mensaje de
ESTE turno, su propio valor (si lo trae), y cómo saber si ese valor es distinto del que ya
había guardado en la sesión. ``invalidate_stale_focus`` aplica la misma regla a todos por
igual: si el mensaje trae su propio valor y no coincide con el guardado, se descarta el
guardado; si no trae nada, se deja como está — así no se rompe un seguimiento por pronombre
("¿y su departamento?") que no nombra nada nuevo.

Añadir un nuevo tipo de dato en el futuro (p. ej. tipo de turno, buzón de correo) es declarar
un ``FocusSlot`` más donde corresponda (ver ``mia.modules.rrhh.common`` para persona y
departamento) y sumarlo a la lista que construye el motor — nunca repetir esta función.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from mia.auth import UserContext
from mia.query.period import ResolvedPeriod
from mia.reporting.planner import planner


@dataclass(frozen=True, slots=True)
class FocusContext:
    message: str
    today: date
    user: UserContext


@dataclass(frozen=True, slots=True)
class FocusSlot:
    key: str
    """Clave en ``session_state`` (p. ej. ``"foco_periodo"``)."""
    extract: Callable[[FocusContext], Any | None]
    """Valor que ESTE mensaje trae para este dato, o ``None`` si no trae nada reconocible."""
    differs: Callable[[Any, Any], bool]
    """``True`` si el valor extraído contradice el ya guardado (y éste debe descartarse)."""


def invalidate_stale_focus(slots: Sequence[FocusSlot], state: dict[str, Any], ctx: FocusContext) -> None:
    for slot in slots:
        stored = state.get(slot.key)
        if stored is None:
            continue
        current = slot.extract(ctx)
        if current is not None and slot.differs(current, stored):
            state.pop(slot.key, None)


def _extract_period(ctx: FocusContext) -> ResolvedPeriod | None:
    return planner.plan(ctx.message, user=ctx.user, today=ctx.today).period


def _period_differs(current: ResolvedPeriod, stored: Any) -> bool:
    if not isinstance(stored, dict) or not stored.get("desde"):
        return False
    stored_end = stored.get("hasta", stored["desde"])
    return bool(current.start.isoformat() != stored["desde"] or current.end.isoformat() != stored_end)


PERIOD_SLOT = FocusSlot("foco_periodo", _extract_period, _period_differs)

"""Decide qué módulo(s) necesita una pregunta, antes de ofrecer sus herramientas al modelo.

Clasificación por vocabulario, no por llamada a LLM: evita una ronda extra de latencia y coste,
y es lo que CLAUDE.md pide explícitamente («enrutado determinista»). El motivo real de filtrar:
medido con datos reales, ofrecer las 82 herramientas de RRHH en cada turno cuesta ~21.000 tokens
fijos, se pregunte lo que se pregunte — la mayoría de preguntas solo necesitan un dominio.

Diseño a prueba de vocabulario incompleto (CLAUDE.md pide tolerar variación de lenguaje natural,
nunca romper un dominio por un fallo de enrutado):
  - Si NINGÚN módulo (ni siquiera "finanzas") reconoce nada en el mensaje, se devuelven TODOS los
    dominios reales — exactamente el comportamiento de antes de filtrar nada. Un hueco en el
    vocabulario solo deja de ahorrar tokens en ese mensaje, nunca le quita una herramienta al
    modelo.
  - Si algo coincidió, se devuelve solo eso (el ahorro real) — incluido el caso de que lo único
    que coincidiera sea "finanzas": no tiene sentido traer las 82 herramientas de RRHH solo
    porque alguien preguntó por una factura.
  - ``rrhh`` (las herramientas de sistema) y ``empleados`` (resolver "la ficha de Juan", que no
    lleva vocabulario de ningún dominio) se incluyen siempre, coincida algo o no.
  - ``finanzas`` (sin herramientas reales todavía) queda fuera de la lista de "dominios reales"
    que se usan para rellenar el fallback de "nada coincidió".
  - Excepción deliberada al fallback anterior: un saludo puro ("hola", "hola mia"...) no es una
    pregunta de negocio con vocabulario no reconocido, es la ausencia de una pregunta de negocio —
    no tiene sentido arrastrar los 82 de RRHH para contestar "hola". Ver ``_is_pure_greeting``.
"""

from __future__ import annotations

import re

from mia.conversation.tools import DEFAULT_MODULE
from mia.text import normalize_key

ALWAYS_ON = frozenset({DEFAULT_MODULE, "empleados"})

_WITHOUT_REAL_TOOLS = frozenset({"finanzas", "it"})
"""Módulos sin herramientas reales todavía: no cuentan para decidir si "nada coincidió"."""

_SOFT_SIGNAL = frozenset({"empleados"})
"""Módulos cuya coincidencia, sola, no cuenta como "se reconoció el dominio real" de la pregunta:
``empleados`` ya se ofrece siempre (``ALWAYS_ON``) y su vocabulario es deliberadamente genérico
("personal", nombres propios…), así que coincide con casi cualquier frase de RRHH — dejar que por
sí solo baste para no caer en el fallback dejaría fuera un dominio real cuyo vocabulario simplemente
no cubría esta frase en concreto (visto con datos reales: "indicadores de rotación de personal"
coincide con "empleados" vía "personal" y debe seguir trayendo también ``analitica``)."""

_GREETING_PHRASES = frozenset(
    {
        "hola",
        "holaa",
        "holaaa",
        "ey",
        "hey",
        "buenas",
        "saludos",
        "buenos dias",
        "buenas tardes",
        "buenas noches",
        "que tal",
        "que tal estas",
        "que tal vas",
        "como estas",
        "como andas",
    }
)
"""Frases completas de saludo puro (la normalización ya ha quitado tildes/puntuación). Comparación
EXACTA contra el mensaje completo, no por subcadena: así "hola, ¿cómo va la nómina de este mes?" no
se confunde con un saludo (tiene contenido de negocio real) y solo cae aquí un saludo sin nada más que
resolver — justo el caso que no debería disparar el fallback de catálogo completo."""


def _matches(keyword: str, normalized_message: str) -> bool:
    """Coincide por palabra completa, no por subcadena: "baja" no debe reconocer "tra-baja-dores"."""
    pattern = r"\b" + re.escape(normalize_key(keyword)) + r"\b"
    return re.search(pattern, normalized_message) is not None


def _is_pure_greeting(normalized_message: str) -> bool:
    """Un saludo sin ninguna otra pregunta de negocio ("hola", "hola mia", "qué tal", también dirigido
    al asistente por su nombre: "mia" a secas). No es "nada reconocido" en el sentido del fallback de
    abajo —no hay ninguna pregunta de negocio esperando dominio—, así que no debe arrastrar el catálogo
    completo de RRHH: basta lo que ya se ofrece siempre (``ALWAYS_ON``)."""
    core = normalized_message
    if core == "mia":
        return True
    if core.endswith(" mia"):
        core = core[: -len(" mia")].strip()
    return core in _GREETING_PHRASES


def select_modules(message: str, module_keywords: dict[str, tuple[str, ...]]) -> set[str]:
    """Los módulos que esta pregunta necesita, además de los que se incluyen siempre."""
    normalized = normalize_key(message)
    if _is_pure_greeting(normalized):
        return ALWAYS_ON
    matched = {module for module, keywords in module_keywords.items() if any(_matches(k, normalized) for k in keywords)}
    if not (matched - _SOFT_SIGNAL):
        # Nada reconocido (o solo señales "blandas" como "empleados"): catálogo completo, igual
        # que si no se filtrara nada. Si al menos "finanzas" coincidió, SÍ cuenta como "algo
        # reconocido" (no cae en este fallback): coincidir con finanzas no debe arrastrar los 82
        # de RRHH, solo añadir ese aviso.
        matched |= {m for m in module_keywords if m not in _WITHOUT_REAL_TOOLS}
    return ALWAYS_ON | matched

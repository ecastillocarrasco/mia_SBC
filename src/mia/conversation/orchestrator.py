"""Decide qué módulo(s) necesita una pregunta, antes de ofrecer sus herramientas al modelo.

Hoy solo hay dos módulos: ``rrhh`` (con herramientas reales) y ``finanzas`` (sin ninguna
todavía). Por eso la clasificación es deliberadamente simple -vocabulario por módulo, no una
llamada a LLM-: evita una ronda extra de latencia y coste, y es lo que CLAUDE.md pide
explícitamente («enrutado determinista»). Cuando haya más módulos con contenido real, esto
puede sustituirse por algo más sofisticado sin que quien lo usa (``conversation/engine.py``)
tenga que cambiar: solo ve ``select_modules(mensaje) -> set[str]``.

``rrhh`` se incluye siempre: es el único módulo con herramientas reales hoy, así que nunca debe
excluirse por un fallo de clasificación. Un módulo sin vocabulario reconocido en el mensaje
simplemente no se añade; nunca se usa esto para QUITAR algo que ya iba a ofrecerse.
"""

from __future__ import annotations

from mia.conversation.tools import DEFAULT_MODULE
from mia.text import normalize_key


def select_modules(message: str, module_keywords: dict[str, tuple[str, ...]]) -> set[str]:
    """Los módulos que esta pregunta necesita, además del módulo por defecto (`rrhh` hoy)."""
    normalized = normalize_key(message)
    selected = {DEFAULT_MODULE}
    for module, keywords in module_keywords.items():
        if module == DEFAULT_MODULE:
            continue
        if any(normalize_key(k) in normalized for k in keywords):
            selected.add(module)
    return selected

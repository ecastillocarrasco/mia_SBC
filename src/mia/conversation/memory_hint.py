"""Bloque de contexto con los recuerdos activos del usuario para el turno actual.

Recuperación pasiva (Memoria Inteligente V1, capacidad 3 — entre conversaciones, sesiones y
mundos): el usuario no tiene que pedir "qué recuerdas de mí" para que un recuerdo guardado se
tenga en cuenta — ``ConversationEngine`` lo añade aquí al contexto de cada turno, igual que el
resto de pistas de ``_prepare_request`` (foco, módulo detectado...). El guardado/borrado
explícito (herramientas que el LLM puede invocar) vive en ``mia.modules.memoria.tools``; este
módulo es del motor de conversación, no de ese dominio, para que ``engine.py`` no dependa de un
paquete de ``mia.modules`` (ver ``mia.data.repositories.MemoryRepository`` por el mismo motivo).
"""

from __future__ import annotations

from mia.data.models import UserMemory


def memory_context_block(items: list[UserMemory], *, max_items: int, max_chars: int) -> str:
    """Vacío si no hay recuerdos (nunca añade una sección vacía al prompt)."""
    if not items:
        return ""
    lines = [
        "\n\n## Recuerdos guardados por este usuario",
        "El usuario pidió expresamente recordar esto en una conversación anterior (puede venir de "
        "2D, 3D, Holograma o mIA Desktop indistintamente). Tenlo en cuenta con naturalidad si es "
        "relevante para lo que pregunta ahora; no lo repitas ni menciones que viene de una lista "
        "salvo que te pregunte explícitamente qué recuerdas de él.",
    ]
    lines += [f"- {item.content}" for item in items[:max_items]]
    block = "\n".join(lines)
    return block[:max_chars]

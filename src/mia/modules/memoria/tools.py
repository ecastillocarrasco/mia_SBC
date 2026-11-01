"""Memoria Inteligente V1: guardar, listar y borrar recuerdos propios, y activar/desactivar la
funcionalidad para el usuario actual.

Alcance reducido deliberado (ver documentación de la capacidad en ``docs/memoria_inteligente.md``):
solo recuerdos que el usuario pide guardar expresamente, sin resumen automático de conversaciones
ni búsqueda semántica. La recuperación pasiva entre conversaciones/sesiones/mundos vive aparte, en
``mia.conversation.engine`` + ``mia.modules.memoria.context`` (no es una herramienta: se añade sola
al contexto de cada turno si el usuario tiene la memoria activada).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mia.auth import Permission
from mia.conversation import Tool, ToolContext, ToolResult, ToolStatus
from mia.data import Database
from mia.data.repositories import MemoryLimitReachedError, MemoryRepository

KEYWORDS = (
    "recuerda que",
    "recuerdame",
    "recuérdame",
    "acuerdate de",
    "acuérdate de",
    "no olvides que",
    "apunta que",
    "memoriza que",
    "olvida eso",
    "olvida que",
    "borra ese recuerdo",
    "que recuerdas de mi",
    "qué recuerdas de mí",
    "mis recuerdos",
    "activa la memoria",
    "desactiva la memoria",
)
"""Vocabulario para el orquestador (ver ``conversation/orchestrator.py``); no exhaustivo — una
frase no reconocida aquí sigue llegando al catálogo completo, nunca se pierde la herramienta."""


class RecordarParams(BaseModel):
    contenido: str = Field(
        min_length=1,
        max_length=500,
        description="Lo que el usuario ha pedido EXPRESAMENTE recordar, en sus propias palabras "
        "(p. ej. «que prefiero los informes en PDF», «que mi reunión de equipo es los jueves»). "
        "Nunca guardes algo que el usuario no haya pedido guardar explícitamente, ni lo resumas "
        "más allá de limpiar muletillas («recuerda que...» → el hecho en sí).",
    )


def recordar(db: Database, *, max_items_per_user: int) -> Tool:
    async def handler(p: RecordarParams, ctx: ToolContext) -> ToolResult:
        async with db.session() as session:
            repo = MemoryRepository(session, max_items_per_user=max_items_per_user)
            if not await repo.is_enabled(ctx.user.user_id):
                return ToolResult(
                    ToolStatus.OK,
                    "La memoria está desactivada para este usuario, así que no se ha guardado "
                    "nada. Puede activarla desde el control de memoria o diciendo «activa la "
                    "memoria» — los recuerdos nuevos solo se guardan con la memoria activada.",
                )
            try:
                await repo.add_memory(ctx.user.user_id, p.contenido)
            except MemoryLimitReachedError:
                return ToolResult(
                    ToolStatus.OK,
                    f"Ya hay {max_items_per_user} recuerdos guardados, el máximo de esta versión. "
                    "Borra alguno antes de añadir uno nuevo.",
                )
        return ToolResult(ToolStatus.OK, "Recuerdo guardado.")

    return Tool(
        "recordar",
        "Guarda algo que el usuario pide EXPRESAMENTE recordar entre conversaciones, sesiones y "
        "mundos (2D, 3D, Holograma, mIA Desktop) — p. ej. «mIA, recuerda que...», «acuérdate de "
        "que...», «no olvides que...», «apunta que...» o variantes similares, no hace falta la "
        "frase exacta. Solo para peticiones explícitas de recordar algo, nunca para deducir o "
        "resumir información personal por tu cuenta.",
        RecordarParams,
        handler,
        permission=Permission.MEMORIA_USAR,
        timeout_seconds=10.0,
    )


class _SinParametros(BaseModel):
    pass


def ver_recuerdos(db: Database) -> Tool:
    async def handler(_: _SinParametros, ctx: ToolContext) -> ToolResult:
        async with db.session() as session:
            repo = MemoryRepository(session)
            enabled = await repo.is_enabled(ctx.user.user_id)
            items = await repo.list_memories(ctx.user.user_id) if enabled else []
        if not enabled:
            return ToolResult(ToolStatus.OK, "La memoria está desactivada: no hay recuerdos activos que mostrar.")
        if not items:
            return ToolResult(ToolStatus.OK, "No hay ningún recuerdo guardado todavía.")
        summary = {"recuerdos": [{"contenido": m.content, "guardado": m.created_at.isoformat()} for m in items]}
        presentation: dict[str, Any] = {
            "type": "memory_list",
            "title": "Recuerdos guardados",
            "columns": ["Recuerdo", "Guardado"],
            "rows": [[m.content, m.created_at.strftime("%d/%m/%Y")] for m in items],
        }
        return ToolResult(ToolStatus.OK, summary, presentation)

    return Tool(
        "ver_recuerdos",
        "Lista los recuerdos que el usuario actual ha pedido guardar (solo los suyos — nunca "
        "los de otro usuario). Úsala para preguntas como «qué recuerdas de mí», «qué me has "
        "guardado», «mis recuerdos» o similares.",
        _SinParametros,
        handler,
        permission=Permission.MEMORIA_USAR,
        timeout_seconds=10.0,
    )


class OlvidarRecuerdoParams(BaseModel):
    contenido: str = Field(
        min_length=1,
        max_length=500,
        description="Qué recuerdo borrar, con las palabras del usuario o muy parecidas a como se "
        "guardó. Se borra cualquier recuerdo cuyo texto contenga esto (sin tildes ni mayúsculas).",
    )


def olvidar_recuerdo(db: Database) -> Tool:
    async def handler(p: OlvidarRecuerdoParams, ctx: ToolContext) -> ToolResult:
        async with db.session() as session:
            repo = MemoryRepository(session)
            matches = await repo.delete_matching(ctx.user.user_id, p.contenido)
        if not matches:
            return ToolResult(ToolStatus.NOT_FOUND, "No se ha encontrado ningún recuerdo que coincida con eso.")
        plural = "s" if len(matches) != 1 else ""
        return ToolResult(ToolStatus.OK, f"Borrado{plural} {len(matches)} recuerdo{plural}.")

    return Tool(
        "olvidar_recuerdo",
        "Borra uno o varios recuerdos guardados del usuario actual cuyo contenido coincida con lo "
        "que indique («olvida que prefiero PDF», «borra el recuerdo de la reunión del jueves»...). "
        "Nunca borra recuerdos de otro usuario.",
        OlvidarRecuerdoParams,
        handler,
        permission=Permission.MEMORIA_USAR,
        audit_resource="memoria",
        timeout_seconds=10.0,
    )


class OlvidarTodoParams(BaseModel):
    confirmar: bool = Field(
        description="True SOLO si el usuario ha confirmado expresamente en este mensaje que quiere "
        "borrar TODOS sus recuerdos, no una suposición tuya. Si no está claro, usa False."
    )


def olvidar_todo(db: Database) -> Tool:
    async def handler(p: OlvidarTodoParams, ctx: ToolContext) -> ToolResult:
        if not p.confirmar:
            return ToolResult(
                ToolStatus.OK, "No se ha borrado nada: pide confirmación explícita antes de borrar todos los recuerdos."
            )
        async with db.session() as session:
            repo = MemoryRepository(session)
            count = await repo.delete_all(ctx.user.user_id)
        return ToolResult(ToolStatus.OK, f"Borrados {count} recuerdo(s). No queda ninguno guardado.")

    return Tool(
        "olvidar_todo",
        "Borra TODOS los recuerdos guardados del usuario actual («olvida todo lo que te he "
        "pedido recordar», «borra todos mis recuerdos»...). Exige que el usuario lo haya "
        "confirmado explícitamente en su mensaje antes de llamarla con confirmar=true.",
        OlvidarTodoParams,
        handler,
        permission=Permission.MEMORIA_USAR,
        audit_resource="memoria",
        timeout_seconds=10.0,
    )


class AjustarMemoriaParams(BaseModel):
    activar: bool = Field(description="True para activar la memoria del usuario, False para desactivarla.")


def ajustar_memoria(db: Database) -> Tool:
    async def handler(p: AjustarMemoriaParams, ctx: ToolContext) -> ToolResult:
        async with db.session() as session:
            repo = MemoryRepository(session)
            await repo.set_enabled(ctx.user.user_id, p.activar)
        if p.activar:
            return ToolResult(
                ToolStatus.OK,
                "Memoria activada: a partir de ahora puedo guardar y recordar lo que me pidas "
                "expresamente, entre conversaciones, sesiones y mundos.",
            )
        return ToolResult(
            ToolStatus.OK,
            "Memoria desactivada: no se guardará ni se usará ningún recuerdo nuevo. Los que ya "
            "tenías guardados se conservan hasta que los borres expresamente.",
        )

    return Tool(
        "ajustar_memoria",
        "Activa o desactiva la Memoria Inteligente del usuario actual («activa la memoria», "
        "«desactiva la memoria», «deja de recordar cosas»...). Desactivada por defecto: sin "
        "activarla, mIA no guarda ni usa ningún recuerdo nuevo (los que ya existieran se "
        "conservan hasta que se borren expresamente).",
        AjustarMemoriaParams,
        handler,
        permission=Permission.MEMORIA_USAR,
        timeout_seconds=10.0,
    )


def register(registry: Any, settings: Any, db: Database) -> None:
    if not settings.memory.enabled:
        return
    with registry.using_module("memoria"):
        registry.register(recordar(db, max_items_per_user=settings.memory.max_items_per_user))
        registry.register(ver_recuerdos(db))
        registry.register(olvidar_recuerdo(db))
        registry.register(olvidar_todo(db))
        registry.register(ajustar_memoria(db))


__all__ = ["KEYWORDS", "register"]

"""Herramientas de sistema: qué puede hacer mIA ahora mismo."""

from __future__ import annotations

from pydantic import BaseModel

from mia.conversation import Tool, ToolContext, ToolRegistry, ToolResult


class SinParametros(BaseModel):
    pass


def register(registry: ToolRegistry) -> None:
    async def capacidades(_: SinParametros, ctx: ToolContext) -> ToolResult:
        return ToolResult.ok(
            {
                "disponible_ahora": registry.capabilities_for(ctx.user),
                "ademas": "Consultas generales fuera de Sunset Beach Club (con búsqueda web).",
                "todavia_no_disponible": list(registry.pending_domains),
                "nota": "Lo no disponible está desactivado o pendiente; no hay fecha comprometida.",
            }
        )

    registry.register(
        Tool(
            name="capacidades",
            description=(
                "Qué consultas puede resolver mIA ahora mismo y cuáles todavía no. Úsala cuando "
                "pregunten qué sabes hacer."
            ),
            params=SinParametros,
            handler=capacidades,
        )
    )

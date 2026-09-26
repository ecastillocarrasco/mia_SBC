"""Herramientas de sistema: lo que mIA puede hacer ahora mismo."""

from __future__ import annotations

from pydantic import BaseModel

from mia.conversation import Tool, ToolContext, ToolRegistry, ToolResult

# Estado de la migración, visible para que mIA no prometa lo que aún no tiene.
PENDING_DOMAINS = (
    "empleados y organización",
    "turnos",
    "vacaciones y saldos",
    "bajas y ausencias",
    "nóminas",
    "documentación firmada",
    "selección y currículums",
    "trabajo temporal",
    "correo",
    "informes PDF/Excel",
)


class SinParametros(BaseModel):
    pass


async def _capacidades(_: SinParametros, ctx: ToolContext) -> ToolResult:
    return ToolResult.ok(
        {
            "disponible_ahora": ["conversación general", "fecha y hora"],
            "en_migracion": list(PENDING_DOMAINS),
            "nota": (
                "Los dominios en migración se irán incorporando por fases; no hay fecha "
                "comprometida y mIA no avisa por su cuenta cuando estén listos."
            ),
            "permisos_del_usuario": sorted(p.value for p in ctx.user.permissions),
        }
    )


def register(registry: ToolRegistry) -> None:
    registry.register(
        Tool(
            name="capacidades",
            description=(
                "Indica qué consultas puede resolver mIA ahora mismo y cuáles están en migración. "
                "Úsala cuando pregunten qué sabes hacer o pidan datos de un dominio que no tienes."
            ),
            params=SinParametros,
            handler=_capacidades,
        )
    )

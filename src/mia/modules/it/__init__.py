"""Módulo IT — sin fuente de datos ni herramientas todavía.

Un dominio más junto a ``rrhh``, ``finanzas`` y ``community`` (mismo nivel), con el mismo patrón
que ``finanzas`` mientras no tiene fuente de datos real: se declara el módulo y su vocabulario
para que el orquestador lo reconozca y avise con naturalidad de que todavía no está disponible,
en vez de dejar que el modelo invente incidencias, equipos o tickets que no existen.

Cuando IT tenga una fuente de datos real (mesa de ayuda, inventario, tickets…), este módulo gana
sus propios dominios con el mismo patrón que ``modules/community`` — el orquestador no necesita
cambiar.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mia.modules import ModuleManifest

if TYPE_CHECKING:
    from mia.conversation.tools import ToolRegistry

MANIFEST = ModuleManifest(
    name="it",
    description="IT / Sistemas: soporte técnico, incidencias, equipos e inventario. Sin fuente "
    "de datos conectada todavía.",
    permissions=(),
    languages=("es",),
    sources=(),
)

KEYWORDS = (
    "it", "informatica", "informática", "sistemas", "soporte tecnico", "soporte técnico",
    "incidencia", "incidencia tecnica", "incidencia técnica", "ticket", "tickets",
    "mesa de ayuda", "helpdesk", "hardware", "software", "ordenador", "portatil", "portátil",
    "impresora", "red wifi", "wifi", "contraseña", "password", "usuario de red", "vpn",
)
"""Vocabulario para que el orquestador reconozca una pregunta de este módulo (CLAUDE.md pide
enrutado determinista; no es una lista exhaustiva, es la que decide si avisar de que el módulo
no está disponible en vez de dejar que el modelo invente datos de IT)."""


def register(registry: ToolRegistry, deps: Any) -> None:
    """Sin fuente de datos real todavía: no registra ninguna herramienta."""
    return

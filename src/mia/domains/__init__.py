"""Dominios funcionales de mIA.

Cada dominio vive en su propio paquete con modelo, repositorio, servicio,
herramientas y tests, y se registra aquí. Los dominios de RRHH (empleados,
turnos, vacaciones, nóminas, documentos, currículums, trabajo temporal y
correo) se incorporan en las fases de migración.
"""

from __future__ import annotations

from mia.conversation import ToolRegistry
from mia.domains import sistema


def build_registry() -> ToolRegistry:
    registry = ToolRegistry(pending_domains=sistema.PENDING_DOMAINS)
    sistema.register(registry)
    return registry

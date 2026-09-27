"""Dominios funcionales de mIA.

Cada dominio vive en su propio paquete con sus herramientas y tests, y se
registra aquí. Los que aún no están migrados se declaran como pendientes para
que mIA no los prometa.
"""

from __future__ import annotations

from mia.conversation import ToolRegistry
from mia.data import Database
from mia.domains import empleados, sistema, turnos, vacaciones
from mia.domains.common import Deps

PENDING_DOMAINS = (
    "nóminas",
    "documentación firmada",
    "selección y currículums",
    "trabajo temporal",
    "correo",
    "informes PDF/Excel",
)


def build_registry(db: Database) -> ToolRegistry:
    deps = Deps(db=db)
    registry = ToolRegistry(pending_domains=PENDING_DOMAINS)
    sistema.register(registry)
    empleados.register(registry, deps)
    turnos.register(registry, deps)
    vacaciones.register(registry, deps)
    return registry

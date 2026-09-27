"""Dominios funcionales de mIA.

Cada dominio vive en su propio paquete con sus herramientas y tests, y se
registra aquí. Los dominios desactivados (MIA_DOMAINS__ENABLED) no se ofrecen al
modelo y se declaran como no disponibles para que mIA no los prometa.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

from mia.conversation import ToolRegistry
from mia.data import Database
from mia.domains import (
    analitica,
    correo,
    curriculums,
    documentos,
    empleados,
    informes,
    nominas,
    sistema,
    trabajo_temporal,
    turnos,
    vacaciones,
)
from mia.domains.common import Deps

DOMAINS: dict[str, tuple[str, Callable[[ToolRegistry, Deps], None]]] = {
    "empleados": ("empleados y organización", empleados.register),
    "turnos": ("turnos y ausencias", turnos.register),
    "vacaciones": ("vacaciones y saldos", vacaciones.register),
    "curriculums": ("selección y currículums", curriculums.register),
    "correo": ("correo del buzón de RRHH", correo.register),
    "nominas": ("nóminas", nominas.register),
    "documentos": ("documentación firmada", documentos.register),
    "trabajo_temporal": ("trabajo temporal", trabajo_temporal.register),
    "analitica": ("panel y analítica de RRHH", analitica.register),
    "informes": ("informes PDF/Excel/PowerPoint", informes.register),
}


def build_registry(
    db: Database,
    stale_after_minutes: int = 30,
    *,
    settings: Any = None,
    llm: Any = None,
    graph: Any = None,
    sharepoint: Any = None,
    enabled: list[str] | None = None,
) -> ToolRegistry:
    active = [d for d in DOMAINS if enabled is None or d in enabled]
    deps = Deps(
        db=db,
        stale_after=timedelta(minutes=stale_after_minutes),
        llm=llm,
        settings=settings,
        graph=graph,
        sharepoint=sharepoint,
    )
    registry = ToolRegistry(pending_domains=tuple(DOMAINS[d][0] for d in DOMAINS if d not in active))
    sistema.register(registry)
    for domain in active:
        DOMAINS[domain][1](registry, deps)
    return registry

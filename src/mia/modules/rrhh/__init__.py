"""Módulo RRHH: el primero de los módulos de conocimiento de la empresa.

Cada dominio (empleados, turnos, vacaciones…) vive en su propio paquete con sus herramientas
y tests, y se registra aquí. Los dominios desactivados (MIA_DOMAINS__ENABLED) no se ofrecen al
modelo y se declaran como no disponibles para que mIA no los prometa.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

from mia.auth import Permission
from mia.conversation import ToolRegistry
from mia.data import Database
from mia.modules import ModuleManifest
from mia.modules.rrhh import (
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
from mia.modules.rrhh.common import Deps

MANIFEST = ModuleManifest(
    name="rrhh",
    description="Recursos Humanos: empleados y organización, turnos y ausencias, vacaciones, "
    "nóminas, documentación firmada, correo del buzón de RRHH, selección y currículums, "
    "trabajo temporal, analítica e informes.",
    permissions=(
        Permission.EMPLEADOS_LEER,
        Permission.TURNOS_LEER,
        Permission.VACACIONES_LEER,
        Permission.NOMINAS_LEER,
        Permission.NOMINAS_IMPORTES,
        Permission.DOCUMENTOS_LEER,
        Permission.DOCUMENTOS_CONTENIDO,
        Permission.CURRICULUMS_LEER,
        Permission.TRABAJO_TEMPORAL_LEER,
        Permission.CORREO_LEER,
        Permission.CORREO_ENVIAR,
        Permission.INFORMES_GENERAR,
        Permission.ADMINISTRAR,
        # PREDICCIONES_LEER no está aquí: hoy no la exige ninguna herramienta de RRHH,
        # está reservada para el futuro módulo predictivo (analytics/).
    ),
    languages=("es",),
    sources=(
        "sharepoint:Empleados",
        "sharepoint:Turnos",
        "sharepoint:Vacaciones",
        "sharepoint:Nominas",
        "sharepoint:DocumentosFirmados",
        "sharepoint:Calendarios",
        "sharepoint:Candidaturas",
        "graph:correo",
    ),
)

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
    # Referencia a sí mismo para los pocos casos (p. ej. redirección interna de informes) en los que una
    # herramienta debe invocar a otra a través del registro — nunca llamando a su handler directamente,
    # para no saltarse la comprobación de permisos, el trazado de diagnóstico ni el timeout que aplica
    # `ToolRegistry.execute()`. `deps.services` ya es el cajón de servicios compartidos del dominio.
    deps.services["registry"] = registry
    sistema.register(registry)
    for domain in active:
        DOMAINS[domain][1](registry, deps)
    return registry

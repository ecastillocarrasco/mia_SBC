"""Contrato común de los módulos de conocimiento de la empresa.

mIA es una plataforma conversacional para toda la organización. Los dominios funcionales son
paquetes independientes (por ejemplo, Community, RRHH, Finanzas e IT); Correo, Legal y otros
dominios deben seguir el mismo contrato al separarse de sus ubicaciones actuales o incorporarse.
Cada módulo declara un :class:`ModuleManifest` con permisos, idiomas y fuentes. Las herramientas
verifican permisos en backend, independientemente de la selección que haga el orquestador.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModuleManifest:
    name: str
    """Identificador corto y estable del módulo (p. ej. «rrhh», «finanzas»)."""
    description: str
    permissions: tuple[str, ...]
    """Los ``Permission`` (``mia.auth``) que alguna herramienta del módulo puede exigir."""
    languages: tuple[str, ...]
    """Idiomas en los que el módulo puede responder hoy (ISO 639-1). Ampliar aquí cuando el
    contenido (no solo la conversación) esté traducido a ese idioma."""
    sources: tuple[str, ...]
    """Fuentes de datos de las que depende, como ``sharepoint:<lista>`` o ``graph:correo``."""

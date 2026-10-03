"""Contrato común de los módulos de conocimiento de la empresa.

mIA deja de ser solo RRHH: a este módulo le seguirán Finanzas, Administración, Legal y
Compliance. Cada módulo declara un :class:`ModuleManifest` (qué permisos exige, qué idiomas
soporta hoy y qué fuentes usa) para que el orquestador de conversación (``conversation/``)
pueda decidir qué módulo o módulos necesita una pregunta antes de cargar sus herramientas.

Hoy solo existe ``rrhh``, así que el enrutado multi-módulo no está implementado todavía
(no hay nada que enrutar); este módulo deja la interfaz lista para cuando lo haya.
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

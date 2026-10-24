"""Dominio de correo corporativo, independiente de RRHH."""

from mia.modules.correo.manifest import MANIFEST
from mia.modules.correo.tools import KEYWORDS, register

__all__ = ["KEYWORDS", "MANIFEST", "register"]

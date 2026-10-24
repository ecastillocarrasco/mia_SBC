"""Contrato declarativo del dominio de correo."""

from mia.auth import Permission
from mia.modules import ModuleManifest

MANIFEST = ModuleManifest(
    name="correo",
    description="Correo corporativo personal: lectura, búsqueda, borradores y envío controlado desde el buzón propio.",
    permissions=(Permission.CORREO_LEER, Permission.CORREO_ENVIAR),
    languages=("es",),
    sources=("graph:correo",),
)

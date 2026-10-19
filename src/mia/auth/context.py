"""Identidad y permisos del usuario.

Cada petición lleva un :class:`UserContext`. Cada herramienta de dominio
declara el :class:`Permission` que exige, y el motor solo ofrece al LLM las
herramientas que el usuario puede usar. Así el modelo nunca llega a ver datos
fuera del alcance del usuario.

Los roles coinciden con los *app roles* que se definirán en Entra ID.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Permission(StrEnum):
    EMPLEADOS_LEER = "empleados:leer"
    TURNOS_LEER = "turnos:leer"
    FICHAJES_LEER = "fichajes:leer"
    """Control de presencia (fichajes): marcas de entrada/salida y su cruce con los turnos
    planificados. Fuente actual: importación manual del Excel de Conectia (A3), solo en
    entornos de prueba — ver ``mia.modules.rrhh.fichajes``."""
    VACACIONES_LEER = "vacaciones:leer"
    NOMINAS_LEER = "nominas:leer"
    NOMINAS_IMPORTES = "nominas:importes"
    """Contenido económico de las nóminas: se lee en el momento y se audita. Desde la decisión explícita
    de indexación de contenido sensible (``DataSettings.index_sensitive_content``), el texto completo de
    la nómina también se extrae, fragmenta y persiste para búsqueda semántica (``buscar_en_nominas``,
    ``mia.modules.rrhh.document_indexing``), igual que los CVs — ya no es cierto que "nunca se guarda"."""
    DOCUMENTOS_LEER = "documentos:leer"
    DOCUMENTOS_CONTENIDO = "documentos:contenido"
    """Contenido de documentos firmados: lectura en el momento (``leer_documento``) y, si
    ``DataSettings.index_sensitive_content`` está activo, también indexación persistente para
    búsqueda semántica (``buscar_en_documentos``), igual que los CVs. NO cubre por sí solo el
    contenido de "Reconocimiento médico" — ver ``DOCUMENTOS_CONTENIDO_MEDICO``."""
    DOCUMENTOS_CONTENIDO_MEDICO = "documentos:contenido_medico"
    """Exigido ADEMÁS de ``DOCUMENTOS_CONTENIDO`` para leer o buscar el CONTENIDO de documentos de
    tipo "Reconocimiento médico" (decisión de negocio: p. ej. el rol "Legal" ve el contenido de
    contratos y similares, nunca el de reconocimientos médicos). La existencia/tipo del documento
    sigue bajo ``DOCUMENTOS_LEER`` sin esta distinción — ver ``mia.modules.rrhh.documentos.tools.
    is_medical_document_type``."""
    CURRICULUMS_LEER = "curriculums:leer"
    TRABAJO_TEMPORAL_LEER = "trabajo_temporal:leer"
    CORREO_LEER = "correo:leer"
    CORREO_ENVIAR = "correo:enviar"
    INFORMES_GENERAR = "informes:generar"
    PREDICCIONES_LEER = "predicciones:leer"
    ADMINISTRAR = "sistema:administrar"


_LECTURA_RRHH = frozenset(
    {
        Permission.EMPLEADOS_LEER,
        Permission.TURNOS_LEER,
        Permission.FICHAJES_LEER,
        Permission.VACACIONES_LEER,
        Permission.DOCUMENTOS_LEER,
        Permission.TRABAJO_TEMPORAL_LEER,
        Permission.INFORMES_GENERAR,
        Permission.PREDICCIONES_LEER,
    }
)

_RRHH_COMPLETO = _LECTURA_RRHH | {
    Permission.NOMINAS_LEER,
    Permission.NOMINAS_IMPORTES,
    Permission.DOCUMENTOS_CONTENIDO,
    Permission.DOCUMENTOS_CONTENIDO_MEDICO,
    Permission.CURRICULUMS_LEER,
    Permission.CORREO_LEER,
    Permission.CORREO_ENVIAR,
}

ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    # Roles de desarrollo/pruebas (``DevIdentityProvider``, ``MIA_AUTH__MODE=dev``) — nunca los
    # usa Entra ID. Se mantienen tal cual: cambiarlos rompería la suite de tests existente.
    "mia.admin": frozenset(Permission),
    "mia.rrhh": _RRHH_COMPLETO,
    "mia.seleccion": frozenset({Permission.CURRICULUMS_LEER, Permission.EMPLEADOS_LEER}),
    "mia.responsable": frozenset({Permission.EMPLEADOS_LEER, Permission.TURNOS_LEER, Permission.VACACIONES_LEER}),
    # App Roles reales de Entra ID (``MIA_AUTH__MODE=entra``): el nombre debe coincidir EXACTO
    # (mayúsculas, puntos) con el valor del App Role definido en el manifiesto de la aplicación.
    # Cada App Role se asigna en Entra ID a una persona o a un grupo de seguridad completo
    # (Enterprise Applications → esta app → "Users and groups" → Assign) — mIA nunca lee el
    # claim ``groups`` directamente, solo ``roles`` (ver ``EntraIdIdentityProvider``).
    "Global": frozenset(Permission),
    "RRHH": _RRHH_COMPLETO,
    "RRHH.NoNominas": _RRHH_COMPLETO - {Permission.NOMINAS_LEER, Permission.NOMINAS_IMPORTES},
    # Alcance confirmado con el usuario: "Administracion" ve empleados y nóminas; "Legal" ve
    # documentos (contratos y similares) pero nunca el contenido de reconocimientos médicos —
    # por eso NO lleva DOCUMENTOS_CONTENIDO_MEDICO (ver ese Permission y is_medical_document_type).
    "Administracion": frozenset({Permission.EMPLEADOS_LEER, Permission.NOMINAS_LEER, Permission.NOMINAS_IMPORTES}),
    "Legal": frozenset({Permission.DOCUMENTOS_LEER, Permission.DOCUMENTOS_CONTENIDO}),
}


class PermissionDeniedError(Exception):
    def __init__(self, permission: Permission) -> None:
        super().__init__(f"Permiso requerido: {permission.value}")
        self.permission = permission


@dataclass(frozen=True, slots=True)
class UserContext:
    user_id: str
    display_name: str
    email: str | None = None
    roles: frozenset[str] = field(default_factory=frozenset)
    auth_method: str = "dev"
    language: str = "es"
    """ISO 639-1 (``mia.core.i18n.SUPPORTED_LANGUAGES``). Por ahora siempre «es»: ningún
    proveedor de identidad la rellena todavía desde una preferencia real del usuario."""

    @property
    def permissions(self) -> frozenset[Permission]:
        granted: set[Permission] = set()
        for role in self.roles:
            granted |= ROLE_PERMISSIONS.get(role, frozenset())
        return frozenset(granted)

    def has(self, permission: Permission | None) -> bool:
        return permission is None or permission in self.permissions

    def require(self, permission: Permission | None) -> None:
        if not self.has(permission):
            assert permission is not None  # noqa: S101  (has() es True para None)
            raise PermissionDeniedError(permission)

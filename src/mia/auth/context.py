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
    VACACIONES_LEER = "vacaciones:leer"
    NOMINAS_LEER = "nominas:leer"
    NOMINAS_IMPORTES = "nominas:importes"
    """Contenido económico de las nóminas: se lee en el momento, se audita y nunca se guarda."""
    DOCUMENTOS_LEER = "documentos:leer"
    DOCUMENTOS_CONTENIDO = "documentos:contenido"
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
        Permission.VACACIONES_LEER,
        Permission.DOCUMENTOS_LEER,
        Permission.TRABAJO_TEMPORAL_LEER,
        Permission.INFORMES_GENERAR,
        Permission.PREDICCIONES_LEER,
    }
)

ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "mia.admin": frozenset(Permission),
    "mia.rrhh": _LECTURA_RRHH
    | {
        Permission.NOMINAS_LEER,
        Permission.NOMINAS_IMPORTES,
        Permission.DOCUMENTOS_CONTENIDO,
        Permission.CURRICULUMS_LEER,
        Permission.CORREO_LEER,
        Permission.CORREO_ENVIAR,
    },
    "mia.seleccion": frozenset({Permission.CURRICULUMS_LEER, Permission.EMPLEADOS_LEER}),
    "mia.responsable": frozenset({Permission.EMPLEADOS_LEER, Permission.TURNOS_LEER, Permission.VACACIONES_LEER}),
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

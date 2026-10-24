"""Configuración pública de autenticación para los clientes web y desktop.

Devuelve el tenant, los IDs públicos de cada cliente, la audiencia API y el scope solicitado.
No devuelve credenciales ni secretos.
"""

from __future__ import annotations

from fastapi import APIRouter

from mia.api.deps import ServicesDep, UserDep
from mia.settings import AuthMode

router = APIRouter(prefix="/api", tags=["autenticación"])


@router.get("/auth/config")
async def auth_config(services: ServicesDep) -> dict[str, object]:
    settings = services.settings.auth
    requires_login = settings.mode is AuthMode.ENTRA
    return {
        "mode": settings.mode.value,
        "requires_login": requires_login,
        "entra": (
            {
                "tenant_id": settings.entra_tenant_id,
                "client_id": settings.entra_client_id,
                "web_client_id": settings.entra_web_client_id,
                "desktop_client_id": settings.entra_desktop_client_id,
                "scope": settings.entra_scope or f"api://{settings.entra_client_id}/access_as_user",
            }
            if requires_login
            else None
        ),
    }


@router.get("/auth/me")
async def auth_me(user: UserDep) -> dict[str, object]:
    """Autenticación (token válido) y autorización (algún permiso asignado) son cosas distintas:
    un usuario de Entra ID puede iniciar sesión correctamente y, pese a ello, no tener ningún App
    Role reconocido en ``ROLE_PERMISSIONS`` — esta es la única forma de que el front-end lo sepa
    ANTES de dejarle usar mIA, en vez de dejarle escribir y que ninguna herramienta responda nunca.
    401 (token inválido o ausente) lo da ya ``UserDep`` antes de llegar aquí."""
    return {
        "user_id": user.user_id,
        "display_name": user.display_name,
        "email": user.email,
        "has_access": bool(user.permissions),
    }

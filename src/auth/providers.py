"""Proveedores de identidad.

* ``dev``: identidad fija configurable (local, test, dev). Bloqueado en producción.
* ``easyauth``: lee la identidad que inyecta la autenticación integrada de Azure
  Container Apps / App Service. La plataforma elimina esas cabeceras si llegan
  del cliente, por lo que solo es fiable detrás de Easy Auth.

La fase de Entra ID añadirá un proveedor que valida el access token (MSAL) sin
cambiar nada fuera de este módulo.
"""

from __future__ import annotations

import base64
import binascii
import json
from typing import Any, Protocol

from fastapi import Request

from mia.auth.context import UserContext
from mia.settings import AuthMode, AuthSettings


class AuthenticationError(Exception):
    """La petición no trae una identidad válida."""


class IdentityProvider(Protocol):
    async def authenticate(self, request: Request) -> UserContext: ...


class DevIdentityProvider:
    def __init__(self, settings: AuthSettings) -> None:
        self._user = UserContext(
            user_id=settings.dev_user_id,
            display_name=settings.dev_display_name,
            email=settings.dev_email,
            roles=frozenset(settings.dev_roles),
            auth_method="dev",
        )

    async def authenticate(self, request: Request) -> UserContext:
        return self._user


class EasyAuthIdentityProvider:
    PRINCIPAL_HEADER = "x-ms-client-principal"

    async def authenticate(self, request: Request) -> UserContext:
        raw = request.headers.get(self.PRINCIPAL_HEADER)
        if not raw:
            raise AuthenticationError("Falta la identidad de Easy Auth")
        try:
            principal: dict[str, Any] = json.loads(base64.b64decode(raw))
        except (binascii.Error, ValueError) as exc:
            raise AuthenticationError("Identidad de Easy Auth no válida") from exc
        claims: dict[str, list[str]] = {}
        for claim in principal.get("claims", []):
            claims.setdefault(str(claim.get("typ", "")), []).append(str(claim.get("val", "")))

        def first(*types: str) -> str | None:
            for typ in types:
                if claims.get(typ):
                    return claims[typ][0]
            return None

        user_id = first("http://schemas.microsoft.com/identity/claims/objectidentifier", "oid")
        if not user_id:
            raise AuthenticationError("La identidad no incluye el identificador de usuario")
        role_claim = principal.get("role_typ", "roles")
        return UserContext(
            user_id=user_id,
            display_name=first("name") or request.headers.get("x-ms-client-principal-name", user_id),
            email=first("preferred_username", "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/upn"),
            roles=frozenset(claims.get(role_claim, []) + claims.get("roles", [])),
            auth_method="easyauth",
        )


def build_identity_provider(settings: AuthSettings) -> IdentityProvider:
    if settings.mode is AuthMode.EASYAUTH:
        return EasyAuthIdentityProvider()
    return DevIdentityProvider(settings)

"""Proveedores de identidad.

* ``dev``: identidad fija configurable (local, test, dev). Bloqueado en producción.
* ``easyauth``: lee la identidad que inyecta la autenticación integrada de Azure
  Container Apps / App Service. La plataforma elimina esas cabeceras si llegan
  del cliente, por lo que solo es fiable detrás de Easy Auth.
* ``entra``: valida el access token (JWT) de Microsoft Entra ID en cada petición,
  directamente contra las claves públicas del tenant (JWKS) — sin pasar por Easy Auth.
  El front-end obtiene el token con MSAL.js; aquí solo se valida y se leen sus claims.
"""

from __future__ import annotations

import base64
import binascii
import json
import time
from typing import Any, Protocol

import httpx
import jwt
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


class EntraIdIdentityProvider:
    """Valida el access token (JWT) de Microsoft Entra ID directamente, sin pasar por Easy Auth.

    Comprueba firma (RS256 contra las claves públicas del tenant, JWKS), emisor, audiencia y
    expiración; lee el identificador de usuario (``oid``) y los app roles del claim configurado
    (``MIA_AUTH__ENTRA_ROLE_CLAIM``, «roles» por defecto) — los mismos nombres de
    :class:`~mia.auth.context.Permission` que ya usan las herramientas de dominio.

    Las claves del tenant se cachean en memoria y se refrescan si llega un ``kid`` que no se
    reconoce (rotación de claves) o si ha pasado el TTL, sin bloquear por cada petición.
    """

    JWKS_TTL_SECONDS = 24 * 60 * 60

    def __init__(self, settings: AuthSettings, *, http_client: httpx.AsyncClient | None = None) -> None:
        if not settings.entra_tenant_id or not settings.entra_client_id:
            raise ValueError("entra_tenant_id y entra_client_id son obligatorios en modo 'entra'")
        self._audience = settings.entra_client_id
        self._role_claim = settings.entra_role_claim
        self._issuer = f"https://login.microsoftonline.com/{settings.entra_tenant_id}/v2.0"
        self._jwks_uri = f"https://login.microsoftonline.com/{settings.entra_tenant_id}/discovery/v2.0/keys"
        self._http = http_client or httpx.AsyncClient(timeout=10)
        self._owns_http = http_client is None
        self._keys: dict[str, Any] = {}
        self._keys_fetched_at: float = 0.0

    async def _signing_key(self, kid: str) -> Any:
        stale = (time.monotonic() - self._keys_fetched_at) > self.JWKS_TTL_SECONDS
        if kid not in self._keys or stale:
            await self._refresh_keys()
        key = self._keys.get(kid)
        if key is None:
            raise AuthenticationError("El token está firmado con una clave que el tenant ya no reconoce")
        return key

    async def _refresh_keys(self) -> None:
        try:
            response = await self._http.get(self._jwks_uri)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AuthenticationError("No se pudieron obtener las claves públicas del tenant") from exc
        self._keys = {
            jwk["kid"]: jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))
            for jwk in response.json().get("keys", [])
            if jwk.get("kty") == "RSA" and jwk.get("kid")
        }
        self._keys_fetched_at = time.monotonic()

    async def authenticate(self, request: Request) -> UserContext:
        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            raise AuthenticationError("Falta el token de Entra ID (cabecera Authorization: Bearer …)")
        token = header[len("bearer ") :].strip()
        try:
            kid = jwt.get_unverified_header(token)["kid"]
        except (jwt.InvalidTokenError, KeyError) as exc:
            raise AuthenticationError("Token de Entra ID mal formado") from exc
        key = await self._signing_key(kid)
        try:
            claims = jwt.decode(
                token,
                key=key,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["exp", "iat", "oid"]},
            )
        except jwt.InvalidTokenError as exc:
            raise AuthenticationError(f"Token de Entra ID no válido: {exc}") from exc
        user_id = str(claims["oid"])
        roles = claims.get(self._role_claim) or []
        if isinstance(roles, str):  # Entra ID manda un único rol como string suelto, no lista
            roles = [roles]
        return UserContext(
            user_id=user_id,
            display_name=str(claims.get("name") or user_id),
            email=claims.get("preferred_username") or claims.get("upn"),
            roles=frozenset(str(r) for r in roles),
            auth_method="entra",
        )

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()


def build_identity_provider(settings: AuthSettings) -> IdentityProvider:
    if settings.mode is AuthMode.EASYAUTH:
        return EasyAuthIdentityProvider()
    if settings.mode is AuthMode.ENTRA:
        return EntraIdIdentityProvider(settings)
    return DevIdentityProvider(settings)

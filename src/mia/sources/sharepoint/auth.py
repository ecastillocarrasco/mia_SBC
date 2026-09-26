"""Token de aplicación para SharePoint con certificado (MSAL, flujo client credentials)."""

from __future__ import annotations

import asyncio
import base64
import time
from pathlib import Path
from typing import Any, Protocol

import msal
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12

from mia.settings import SharePointSettings


class SharePointAuthError(Exception):
    """No se ha podido obtener un token de Entra ID."""


class TokenProvider(Protocol):
    async def token(self, *, force_refresh: bool = False) -> str: ...


class StaticTokenProvider:
    """Token fijo (tests)."""

    def __init__(self, value: str = "test-token") -> None:
        self.value = value
        self.refreshes = 0

    async def token(self, *, force_refresh: bool = False) -> str:
        if force_refresh:
            self.refreshes += 1
        return self.value


def _private_key_pem(settings: SharePointSettings) -> str:
    if settings.cert_pem_path:
        return Path(settings.cert_pem_path).read_text(encoding="utf-8")
    if settings.cert_pfx_base64 is not None and settings.cert_pfx_base64.get_secret_value():
        pfx = base64.b64decode(settings.cert_pfx_base64.get_secret_value())
    elif settings.cert_pfx_path:
        pfx = Path(settings.cert_pfx_path).read_bytes()
    else:
        raise SharePointAuthError("Falta el certificado (MIA_SHAREPOINT__CERT_PFX_PATH o _BASE64)")
    password = settings.cert_pfx_password.get_secret_value().encode() or None
    try:
        key, cert, _ = pkcs12.load_key_and_certificates(pfx, password)
    except ValueError as exc:
        raise SharePointAuthError("No se ha podido abrir el PFX: revisa la contraseña") from exc
    if key is None or cert is None:
        raise SharePointAuthError("El PFX no contiene clave privada y certificado")
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode("ascii")


class CertificateTokenProvider:
    REFRESH_MARGIN_SECONDS = 300

    def __init__(self, settings: SharePointSettings) -> None:
        self._settings = settings
        self._app: msal.ConfidentialClientApplication | None = None
        self._token: str | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    def _client(self) -> msal.ConfidentialClientApplication:
        if self._app is None:
            self._app = msal.ConfidentialClientApplication(
                client_id=self._settings.client_id,
                authority=f"https://login.microsoftonline.com/{self._settings.tenant_id}",
                client_credential={
                    "thumbprint": self._settings.cert_thumbprint,
                    "private_key": _private_key_pem(self._settings),
                },
            )
        return self._app

    def _acquire(self) -> dict[str, Any]:
        scope = [f"https://{self._settings.host}/.default"]
        result: dict[str, Any] = self._client().acquire_token_for_client(scopes=scope)
        return result

    async def token(self, *, force_refresh: bool = False) -> str:
        async with self._lock:
            if (
                not force_refresh
                and self._token
                and time.time() < self._expires_at - self.REFRESH_MARGIN_SECONDS
            ):
                return self._token
            result = await asyncio.to_thread(self._acquire)
            token = result.get("access_token")
            if not token:
                detail = result.get("error_description") or result.get("error") or "sin detalle"
                raise SharePointAuthError(f"Entra ID no ha emitido token: {detail}")
            self._token = str(token)
            self._expires_at = time.time() + int(result.get("expires_in", 3600))
            return self._token

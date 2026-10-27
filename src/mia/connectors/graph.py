"""Cliente Microsoft Graph con OBO delegado; app-only queda para desarrollo/pruebas."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from urllib.parse import quote

import httpx
import msal

from mia.auth.context import UserContext
from mia.connectors.sharepoint.auth import TokenProvider, _private_key_pem
from mia.settings import SharePointSettings

GRAPH = "https://graph.microsoft.com/v1.0"
_RETRY = {429, 500, 502, 503, 504}


class GraphError(Exception):
    """Error al consultar Microsoft Graph."""


class GraphClient:
    def __init__(
        self,
        tokens: TokenProvider,
        *,
        timeout_seconds: float = 30.0,
        max_retries: int = 4,
        transport: httpx.AsyncBaseTransport | None = None,
        delegated_settings: SharePointSettings | None = None,
        delegated_client_id: str | None = None,
        delegated_tenant_id: str | None = None,
        allow_app_only: bool = True,
    ) -> None:
        self._tokens = tokens
        self._delegated_settings = delegated_settings
        self._delegated_client_id = delegated_client_id
        self._delegated_tenant_id = delegated_tenant_id
        self._allow_app_only = allow_app_only
        self._delegated_app: msal.ConfidentialClientApplication | None = None
        self._delegated_cache: dict[str, tuple[str, float]] = {}
        self._delegated_lock = asyncio.Lock()
        self._max_retries = max_retries
        self._http = httpx.AsyncClient(
            base_url=GRAPH, timeout=httpx.Timeout(timeout_seconds, connect=10.0), transport=transport
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    @staticmethod
    def user_path(mailbox: str) -> str:
        return f"/users/{quote(mailbox, safe='@')}"

    async def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        user: UserContext | None = kwargs.pop("user", None)
        extra_headers = kwargs.pop("headers", None) or {}
        if (user is None or user.auth_method == "dev") and not self._allow_app_only:
            raise GraphError("Graph app-only está deshabilitado; esta operación requiere una sesión delegada")
        refreshed = False
        for attempt in range(self._max_retries + 1):
            token = (
                await self._delegated_token(user, force_refresh=refreshed)
                if user is not None and user.auth_method != "dev"
                else await self._tokens.token(force_refresh=refreshed)
            )
            headers = {"Authorization": f"Bearer {token}", **extra_headers}
            try:
                response = await self._http.request(method, path, headers=headers, **kwargs)
            except httpx.HTTPError as exc:
                if attempt >= self._max_retries:
                    raise GraphError(f"No se ha podido conectar con Microsoft Graph: {exc}") from exc
                await asyncio.sleep(min(2**attempt, 20))
                continue
            if response.status_code == 401 and not refreshed:
                refreshed = True
                continue
            if response.status_code in _RETRY and attempt < self._max_retries:
                retry_after = response.headers.get("Retry-After", "")
                await asyncio.sleep(min(float(retry_after) if retry_after.isdigit() else 2**attempt, 30))
                continue
            if response.status_code >= 400:
                if response.status_code == 403:
                    raise GraphError("La cuenta conectada no tiene permiso para acceder al buzón solicitado (HTTP 403)")
                if response.status_code == 404:
                    raise GraphError(
                        "No se ha encontrado el buzón solicitado o no está disponible para esta cuenta (HTTP 404)"
                    )
                raise GraphError(f"Graph HTTP {response.status_code}: {response.text[:300]}")
            if response.status_code == 204 or not response.content:
                return {}
            payload: dict[str, Any] = response.json()
            return payload
        raise GraphError("Se agotaron los reintentos con Microsoft Graph")  # pragma: no cover

    def _delegated_client(self) -> msal.ConfidentialClientApplication:
        settings = self._delegated_settings
        if settings is None or not settings.app_credentials_configured:
            raise GraphError("OBO de Graph no está configurado: falta el certificado de la aplicación")
        if self._delegated_app is None:
            self._delegated_app = msal.ConfidentialClientApplication(
                client_id=self._delegated_client_id or settings.client_id,
                authority=f"https://login.microsoftonline.com/{self._delegated_tenant_id or settings.tenant_id}",
                client_credential={
                    "thumbprint": settings.cert_thumbprint,
                    "private_key": _private_key_pem(settings),
                },
            )
        return self._delegated_app

    async def _delegated_token(self, user: UserContext, *, force_refresh: bool = False) -> str:
        if not user.graph_assertion:
            raise GraphError("La sesión no contiene un token de usuario válido para acceder a Graph")
        assertion = user.graph_assertion
        async with self._delegated_lock:
            cached = self._delegated_cache.get(user.user_id)
            if not force_refresh and cached and cached[1] > time.time() + 60:
                return cached[0]
            if force_refresh:
                self._delegated_cache.pop(user.user_id, None)
            result = await asyncio.to_thread(
                self._delegated_client().acquire_token_on_behalf_of,
                user_assertion=assertion,
                scopes=["https://graph.microsoft.com/.default"],
            )
            token = result.get("access_token")
            if not token:
                error = result.get("error") or "OBO failed"
                description = result.get("error_description") or "Entra ID no emitió un token delegado para Graph"
                raise GraphError(f"{error}: {description[:300]}")
            expires_at = time.time() + int(result.get("expires_in", 3600))
            self._delegated_cache[user.user_id] = (str(token), expires_at)
            if len(self._delegated_cache) > 512:
                now = time.time()
                self._delegated_cache = {key: value for key, value in self._delegated_cache.items() if value[1] > now}
            return str(token)

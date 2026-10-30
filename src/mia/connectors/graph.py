"""Cliente Microsoft Graph con OBO delegado; app-only queda para desarrollo/pruebas."""

from __future__ import annotations

import asyncio
import re
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
_CALENDAR_SCOPES = frozenset(
    {
        "Calendars.Read",
        "Calendars.ReadBasic",
        "Calendars.Read.Shared",
        "Calendars.ReadWrite",
        "Calendars.ReadWrite.Shared",
    }
)


class GraphError(Exception):
    """Error al consultar Microsoft Graph."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
        entra_codes: tuple[int, ...] = (),
        calendar_scopes: tuple[str, ...] | None = None,
        obo_client_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code if code and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", code) else None
        self.entra_codes = tuple(value for value in entra_codes if type(value) is int and 0 < value < 10**10)
        self.calendar_scopes = calendar_scopes
        self.obo_client_id = obo_client_id


def _error_code(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    error = payload.get("error") if isinstance(payload, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    return code if isinstance(code, str) else None


class GraphMutationUncertain(GraphError):
    """La escritura puede haberse aplicado: no se debe repetir automáticamente."""


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
        self._delegated_scope_cache: dict[str, tuple[str, ...] | None] = {}
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

    async def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:  # noqa: PLR0912
        user: UserContext | None = kwargs.pop("user", None)
        retry_safe: bool = kwargs.pop("retry_safe", True)
        calendar_diagnostics: bool = kwargs.pop("calendar_diagnostics", False)
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
                if not retry_safe:
                    raise GraphMutationUncertain("Resultado de escritura desconocido; requiere reconciliación") from exc
                if attempt >= self._max_retries:
                    raise GraphError(
                        f"No se ha podido conectar con Microsoft Graph: {exc}", code="connection_failed"
                    ) from exc
                await asyncio.sleep(min(2**attempt, 20))
                continue
            if response.status_code == 401 and not refreshed:
                refreshed = True
                continue
            if response.status_code in _RETRY and attempt < self._max_retries:
                if not retry_safe:
                    raise GraphMutationUncertain("Graph no confirmó la escritura; no se ha repetido")
                retry_after = response.headers.get("Retry-After", "")
                await asyncio.sleep(min(float(retry_after) if retry_after.isdigit() else 2**attempt, 30))
                continue
            if response.status_code >= 400:
                details = self._calendar_authorization(user) if calendar_diagnostics else {}
                if not retry_safe and response.status_code in _RETRY:
                    raise GraphMutationUncertain("Graph no confirmó la escritura; no se ha repetido")
                if response.status_code == 403:
                    raise GraphError(
                        "La cuenta conectada no tiene permiso para acceder al buzón solicitado (HTTP 403)",
                        status_code=403,
                        code=_error_code(response),
                        **details,
                    )
                if response.status_code == 404:
                    raise GraphError(
                        "No se ha encontrado el buzón solicitado o no está disponible para esta cuenta (HTTP 404)",
                        status_code=404,
                        code=_error_code(response),
                        **details,
                    )
                raise GraphError(
                    f"Graph HTTP {response.status_code}: {response.text[:300]}",
                    status_code=response.status_code,
                    code=_error_code(response),
                    **details,
                )
            if response.status_code == 204 or not response.content:
                return {}
            payload: dict[str, Any] = response.json()
            return payload
        raise GraphError("Se agotaron los reintentos con Microsoft Graph")  # pragma: no cover

    def _calendar_authorization(self, user: UserContext | None) -> dict[str, Any]:
        """Solo metadatos de MSAL; no decodifica ni expone el access token."""
        return {
            "calendar_scopes": self._delegated_scope_cache.get(user.user_id) if user else None,
            "obo_client_id": self._delegated_client_id
            or (self._delegated_settings.client_id if self._delegated_settings is not None else None),
        }

    def _delegated_client(self) -> msal.ConfidentialClientApplication:
        settings = self._delegated_settings
        if settings is None or not settings.app_credentials_configured:
            raise GraphError(
                "OBO de Graph no está configurado: falta el certificado de la aplicación", code="obo_not_configured"
            )
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
            raise GraphError(
                "La sesión no contiene un token de usuario válido para acceder a Graph", code="missing_user_assertion"
            )
        assertion = user.graph_assertion
        async with self._delegated_lock:
            cached = self._delegated_cache.get(user.user_id)
            if not force_refresh and cached and cached[1] > time.time() + 60:
                return cached[0]
            if force_refresh:
                self._delegated_cache.pop(user.user_id, None)
                self._delegated_scope_cache.pop(user.user_id, None)
            result = await asyncio.to_thread(
                self._delegated_client().acquire_token_on_behalf_of,
                user_assertion=assertion,
                scopes=["https://graph.microsoft.com/.default"],
            )
            token = result.get("access_token")
            if not token:
                error = result.get("error") or "OBO failed"
                description = result.get("error_description") or "Entra ID no emitió un token delegado para Graph"
                raw_codes = result.get("error_codes")
                codes = tuple(raw_codes) if isinstance(raw_codes, list) else ()
                raise GraphError(f"{error}: {description[:300]}", code=str(error), entra_codes=codes)
            expires_at = time.time() + int(result.get("expires_in", 3600))
            scope = result.get("scope")
            self._delegated_scope_cache[user.user_id] = (
                tuple(sorted({value.rsplit("/", 1)[-1] for value in scope.split()} & _CALENDAR_SCOPES))
                if isinstance(scope, str)
                else None
            )
            self._delegated_cache[user.user_id] = (str(token), expires_at)
            if len(self._delegated_cache) > 512:
                now = time.time()
                self._delegated_cache = {key: value for key, value in self._delegated_cache.items() if value[1] > now}
                self._delegated_scope_cache = {
                    key: value for key, value in self._delegated_scope_cache.items() if key in self._delegated_cache
                }
            return str(token)

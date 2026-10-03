"""Cliente mínimo de Microsoft Graph (aplicación con certificado), para el correo."""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import quote

import httpx

from mia.connectors.sharepoint.auth import TokenProvider

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
    ) -> None:
        self._tokens = tokens
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
        refreshed = False
        for attempt in range(self._max_retries + 1):
            token = await self._tokens.token(force_refresh=refreshed)
            headers = {"Authorization": f"Bearer {token}", **(kwargs.pop("headers", None) or {})}
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
                raise GraphError(f"Graph HTTP {response.status_code}: {response.text[:300]}")
            if response.status_code == 204 or not response.content:
                return {}
            payload: dict[str, Any] = response.json()
            return payload
        raise GraphError("Se agotaron los reintentos con Microsoft Graph")  # pragma: no cover

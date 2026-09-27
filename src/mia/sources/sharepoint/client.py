"""Cliente REST de SharePoint: paginación, registro de cambios y reintentos.

* Lectura completa: sigue ``odata.nextLink`` (paginación por ID, sin límite de
  vista de lista, sin filtros que provoquen throttling).
* Incremental: registro de cambios de la lista (``GetChanges`` con change token),
  que informa de altas, modificaciones y **borrados** sin depender de índices.
* Reintentos con ``Retry-After`` ante 429/503 y renovación del token ante 401.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

from mia.observability import get_logger
from mia.sources.sharepoint.auth import TokenProvider

log = get_logger(__name__)

_JSON = "application/json;odata=nometadata"
_RETRY_STATUS = {429, 500, 502, 503, 504}
_IDS_PER_REQUEST = 40


class SharePointError(Exception):
    """Error al consultar SharePoint."""


class ChangeTokenExpiredError(SharePointError):
    """El change token ya no es válido (SharePoint conserva el registro de cambios un tiempo limitado)."""


@dataclass(frozen=True, slots=True)
class Change:
    item_id: int
    deleted: bool


def _escape(title: str) -> str:
    return title.replace("'", "''")


class SharePointClient:
    def __init__(
        self,
        *,
        site_url: str,
        tokens: TokenProvider,
        timeout_seconds: float = 30.0,
        page_size: int = 2000,
        max_retries: int = 5,
        concurrency: int = 4,
        transport: httpx.AsyncBaseTransport | None = None,
        backoff_base: float = 1.0,
    ) -> None:
        self._site = site_url.rstrip("/")
        self._tokens = tokens
        self._page_size = page_size
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._semaphore = asyncio.Semaphore(concurrency)
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds, connect=10.0), transport=transport
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    def _list_url(self, title: str) -> str:
        return f"{self._site}/_api/web/lists/getbytitle('{_escape(title)}')"

    async def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        refreshed = False
        for attempt in range(self._max_retries + 1):
            headers = {
                "Authorization": f"Bearer {await self._tokens.token(force_refresh=refreshed)}",
                "Accept": _JSON,
            }
            headers.update(kwargs.pop("headers", {}) or {})
            try:
                async with self._semaphore:
                    response = await self._http.request(method, url, headers=headers, **kwargs)
            except httpx.HTTPError as exc:
                if attempt >= self._max_retries:
                    raise SharePointError(f"No se ha podido conectar con SharePoint: {exc}") from exc
                await self._sleep(attempt, None)
                continue
            if response.status_code == 401 and not refreshed:
                refreshed = True
                continue
            if response.status_code in _RETRY_STATUS and attempt < self._max_retries:
                log.warning("sharepoint.retry", status=response.status_code, attempt=attempt + 1)
                await self._sleep(attempt, response.headers.get("Retry-After"))
                continue
            if response.status_code >= 400:
                body = response.text[:500]
                if "change token" in body.lower() or "SPChangeToken" in body:
                    raise ChangeTokenExpiredError(body)
                raise SharePointError(f"SharePoint HTTP {response.status_code}: {body}")
            try:
                payload: dict[str, Any] = response.json()
            except ValueError as exc:
                raise SharePointError("SharePoint no ha devuelto JSON válido") from exc
            return payload
        raise SharePointError("Se agotaron los reintentos con SharePoint")  # pragma: no cover

    async def _sleep(self, attempt: int, retry_after: str | None) -> None:
        if retry_after and retry_after.isdigit():
            delay = float(retry_after)
        else:
            delay = self._backoff_base * (2**attempt) + random.uniform(0, self._backoff_base)  # noqa: S311
        await asyncio.sleep(min(delay, 60.0))

    async def iter_items(
        self, title: str, *, select: str, expand: str | None = None, filter_expr: str | None = None
    ) -> AsyncIterator[list[dict[str, Any]]]:
        """Recorre todos los elementos de la lista, página a página."""
        query: dict[str, Any] = {"$select": select, "$top": self._page_size}
        if expand:
            query["$expand"] = expand
        if filter_expr:
            query["$filter"] = filter_expr
        params: dict[str, Any] | None = query
        url: str | None = f"{self._list_url(title)}/items"
        seen: set[str] = set()
        while url:
            if url in seen:
                raise SharePointError(f"Paginación repetida en la lista {title}")
            seen.add(url)
            payload = await self._request("GET", url, params=params)
            params = None  # el enlace de continuación ya incluye la consulta
            page = payload.get("value", [])
            if not isinstance(page, list):
                raise SharePointError(f"Respuesta inesperada al paginar {title}")
            yield page
            next_link = payload.get("odata.nextLink") or payload.get("@odata.nextLink")
            url = str(next_link) if next_link else None

    async def items_by_id(
        self, title: str, ids: list[int], *, select: str, expand: str | None = None
    ) -> list[dict[str, Any]]:
        """Recupera elementos concretos por ID (columna siempre indexada)."""
        results: list[dict[str, Any]] = []
        for start in range(0, len(ids), _IDS_PER_REQUEST):
            chunk = ids[start : start + _IDS_PER_REQUEST]
            expr = " or ".join(f"ID eq {int(i)}" for i in chunk)
            async for page in self.iter_items(title, select=select, expand=expand, filter_expr=expr):
                results.extend(page)
        return results

    async def current_change_token(self, title: str) -> str:
        payload = await self._request("GET", self._list_url(title), params={"$select": "CurrentChangeToken"})
        token = (payload.get("CurrentChangeToken") or {}).get("StringValue")
        if not token:
            raise SharePointError(f"La lista {title} no devuelve CurrentChangeToken")
        return str(token)

    async def changes_since(
        self, title: str, token: str, *, fetch_limit: int = 1000
    ) -> tuple[list[Change], str]:
        """Cambios de elementos desde ``token`` (paginando el registro). Devuelve cambios y nuevo token."""
        latest: dict[int, Change] = {}
        current = token
        while True:
            body = {
                "query": {
                    "__metadata": {"type": "SP.ChangeQuery"},
                    "Add": True,
                    "Update": True,
                    "DeleteObject": True,
                    "Restore": True,
                    "Item": True,
                    # En OData verbose los Edm.Int64 viajan como texto; como número SharePoint da 400.
                    "FetchLimit": str(fetch_limit),
                    "ChangeTokenStart": {"__metadata": {"type": "SP.ChangeToken"}, "StringValue": current},
                }
            }
            payload = await self._request(
                "POST",
                f"{self._list_url(title)}/GetChanges",
                json=body,
                headers={"Content-Type": "application/json;odata=verbose"},
            )
            entries = payload.get("value", [])
            for entry in entries:
                token_value = (entry.get("ChangeToken") or {}).get("StringValue")
                if token_value:
                    current = str(token_value)
                item_id = entry.get("ItemId")
                if item_id is None:
                    continue
                # ChangeType: 1 alta, 2 modificación, 3 borrado, 7 restauración. Prevalece el último.
                latest[int(item_id)] = Change(int(item_id), deleted=int(entry.get("ChangeType") or 0) == 3)
            if len(entries) < fetch_limit:
                return list(latest.values()), current

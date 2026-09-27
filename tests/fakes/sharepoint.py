"""SharePoint simulado en memoria: listas, paginación, registro de cambios y fallos."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import unquote

import httpx


class FakeSharePoint:
    def __init__(self, page_size: int = 2) -> None:
        self.lists: dict[str, dict[int, dict[str, Any]]] = {}
        self.log: dict[str, list[tuple[int, int, int]]] = {}  # (seq, change_type, item_id)
        self.seq = 0
        self.page_size = page_size
        self.fail_next: list[int] = []
        self.expired_tokens: set[str] = set()
        self.requests: list[httpx.Request] = []
        self.files: dict[str, bytes] = {}

    # --------------------------------------------------------------- datos
    def _log(self, title: str, change_type: int, item_id: int) -> None:
        self.seq += 1
        self.log.setdefault(title, []).append((self.seq, change_type, item_id))

    def put(self, title: str, item: dict[str, Any]) -> None:
        items = self.lists.setdefault(title, {})
        change = 2 if item["ID"] in items else 1
        items[item["ID"]] = item
        self._log(title, change, item["ID"])

    def remove(self, title: str, item_id: int) -> None:
        self.lists.get(title, {}).pop(item_id, None)
        self._log(title, 3, item_id)

    # --------------------------------------------------------------- HTTP
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail_next:
            return httpx.Response(self.fail_next.pop(0), headers={"Retry-After": "0"}, text="fallo simulado")
        path = unquote(request.url.path)
        file_match = re.search(r"GetFileByServerRelativeUrl\('(.+?)'\)/\$value$", path)
        if file_match:
            content = self.files.get(file_match.group(1).replace("''", "'"))
            return httpx.Response(200, content=content) if content is not None else httpx.Response(404)
        match = re.search(r"getbytitle\('(.+?)'\)(.*)$", path)
        assert match, path
        title, rest = match.group(1).replace("''", "'"), match.group(2)
        if rest == "" and request.method == "GET":
            return httpx.Response(200, json={"CurrentChangeToken": {"StringValue": f"t{self.seq}"}})
        if rest == "/GetChanges":
            return self._changes(title, json.loads(request.content))
        if rest == "/items":
            return self._items(title, request)
        return httpx.Response(404, text="ruta no simulada")

    def _changes(self, title: str, body: dict[str, Any]) -> httpx.Response:
        token = body["query"]["ChangeTokenStart"]["StringValue"]
        if token in self.expired_tokens:
            return httpx.Response(400, text="The change token refers to a time before the start of the log")
        start = int(token[1:])
        raw_limit = body["query"].get("FetchLimit", "1000")
        if not isinstance(raw_limit, str):  # igual que SharePoint real
            return httpx.Response(
                400, text="No se puede convertir un valor primitivo en el tipo esperado 'Edm.Int64'"
            )
        limit = int(raw_limit)
        entries = [
            {"ChangeType": ct, "ItemId": item_id, "ChangeToken": {"StringValue": f"t{seq}"}}
            for seq, ct, item_id in self.log.get(title, [])
            if seq > start
        ][:limit]
        return httpx.Response(200, json={"value": entries})

    def _items(self, title: str, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        items = sorted(self.lists.get(title, {}).values(), key=lambda i: i["ID"])
        if "$filter" in params:
            wanted = {int(x) for x in re.findall(r"ID eq (\d+)", params["$filter"])}
            items = [i for i in items if i["ID"] in wanted]
        after = int(params.get("p_ID", 0))
        items = [i for i in items if i["ID"] > after]
        page, rest = items[: self.page_size], items[self.page_size :]
        payload: dict[str, Any] = {"value": page}
        if rest:
            filt = f"&$filter={params['$filter']}" if "$filter" in params else ""
            payload["odata.nextLink"] = (
                f"{request.url.scheme}://{request.url.host}{request.url.path}?p_ID={page[-1]['ID']}{filt}"
            )
        return httpx.Response(200, json=payload)

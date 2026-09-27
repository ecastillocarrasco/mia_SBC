"""Registro de herramientas que el LLM puede usar.

Cada dominio (turnos, vacaciones, nóminas…) expone herramientas tipadas.
El modelo decide cuál usar y con qué parámetros; la ejecución es código
determinista, validado y auditado.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ValidationError

from mia.auth import Permission, UserContext
from mia.llm import ToolCall, ToolSchema
from mia.observability import get_logger

log = get_logger(__name__)


class ToolStatus(StrEnum):
    OK = "ok"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"
    INVALID_ARGUMENTS = "invalid_arguments"
    PERMISSION_DENIED = "permission_denied"
    SOURCE_UNAVAILABLE = "source_unavailable"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ToolContext:
    user: UserContext
    request_id: str | None
    now: datetime
    session_state: dict[str, Any] = field(default_factory=dict)
    user_message: str = ""
    """Mensaje del usuario en este turno (para acciones que exigen confirmación explícita)."""


@dataclass(frozen=True, slots=True)
class ToolResult:
    status: ToolStatus
    summary: Any
    """Lo que ve el LLM: compacto, sin campos innecesarios."""
    presentation: dict[str, Any] | None = None
    """Lo que pinta la interfaz (tabla, ficha 360…). El LLM no lo reescribe."""
    state_updates: dict[str, Any] = field(default_factory=dict)
    """Cambios de foco conversacional (persona, departamento, periodo…)."""

    @classmethod
    def ok(cls, summary: Any, presentation: dict[str, Any] | None = None, **state: Any) -> ToolResult:
        return cls(ToolStatus.OK, summary, presentation, state)


Handler = Callable[[Any, ToolContext], Awaitable[ToolResult]]


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    params: type[BaseModel]
    handler: Handler
    permission: Permission | None = None
    audit_resource: str | None = None
    """Si se indica, cada uso queda en el registro de auditoría (datos personales)."""
    timeout_seconds: float = 20.0

    def schema(self) -> ToolSchema:
        return ToolSchema(self.name, self.description, self.params.model_json_schema())


@dataclass(frozen=True, slots=True)
class ToolExecution:
    call: ToolCall
    result: ToolResult
    elapsed_ms: int
    audit_resource: str | None

    def as_llm_output(self) -> str:
        return json.dumps(
            {"estado": self.result.status.value, "resultado": self.result.summary},
            ensure_ascii=False,
            default=str,
        )


class ToolRegistry:
    def __init__(self, pending_domains: tuple[str, ...] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        self.pending_domains = pending_domains
        """Dominios que mIA todavía no puede consultar (se declaran para que no los prometa)."""

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Herramienta duplicada: {tool.name}")
        self._tools[tool.name] = tool

    def names(self) -> list[str]:
        return sorted(self._tools)

    def capabilities_for(self, user: UserContext) -> str:
        """Estado real de capacidades, calculado en código: el modelo no lo deduce."""
        tools = [t for t in self._tools.values() if user.has(t.permission)]
        lines = ["Herramientas disponibles ahora (esta lista es completa):"]
        lines += [f"- {t.name}: {t.description.split('. ')[0]}" for t in tools] or ["- ninguna"]
        if self.pending_domains:
            lines.append("Dominios que TODAVÍA NO puedes consultar: " + ", ".join(self.pending_domains) + ".")
        return "\n".join(lines)

    def schemas_for(self, user: UserContext) -> list[ToolSchema]:
        """Solo las herramientas que el usuario puede usar: el LLM no ve el resto."""
        return [tool.schema() for tool in self._tools.values() if user.has(tool.permission)]

    async def execute(self, call: ToolCall, ctx: ToolContext) -> ToolExecution:
        started = time.perf_counter()
        tool = self._tools.get(call.name)
        result = await self._run(tool, call, ctx)
        elapsed = int((time.perf_counter() - started) * 1000)
        log.info("tool.executed", tool=call.name, status=result.status.value, elapsed_ms=elapsed)
        return ToolExecution(call, result, elapsed, tool.audit_resource if tool else None)

    async def execute_all(self, calls: list[ToolCall], ctx: ToolContext) -> list[ToolExecution]:
        return list(await asyncio.gather(*(self.execute(call, ctx) for call in calls)))

    @staticmethod
    async def _run(tool: Tool | None, call: ToolCall, ctx: ToolContext) -> ToolResult:
        if tool is None:
            return ToolResult(ToolStatus.ERROR, f"No existe la herramienta {call.name}")
        if not ctx.user.has(tool.permission):
            return ToolResult(ToolStatus.PERMISSION_DENIED, "El usuario no tiene permiso para esta consulta")
        try:
            params = tool.params.model_validate_json(call.arguments or "{}")
        except ValidationError as exc:
            errors = [{"campo": ".".join(map(str, e["loc"])), "error": e["msg"]} for e in exc.errors()]
            return ToolResult(ToolStatus.INVALID_ARGUMENTS, errors)
        try:
            return await asyncio.wait_for(tool.handler(params, ctx), timeout=tool.timeout_seconds)
        except TimeoutError:
            return ToolResult(ToolStatus.SOURCE_UNAVAILABLE, "La fuente de datos no respondió a tiempo")
        except Exception:
            log.exception("tool.failed", tool=tool.name)
            return ToolResult(ToolStatus.ERROR, "Error técnico al consultar la fuente de datos")


LAST_TABLE = "ultima_presentacion"


def remember_table(state: dict[str, Any], presentation: dict[str, Any] | None, max_rows: int) -> None:
    """Guarda el último resultado mostrado (tabla, panel, ficha 360…) para convertirlo en informe."""
    if not presentation or presentation.get("type") in {None, "download"}:
        return
    stored = dict(presentation)
    if stored.get("type") == "table":
        stored["rows"] = list(stored.get("rows") or [])[:max_rows]
    for sub_table in stored.get("tables") or []:
        sub_table["rows"] = list(sub_table.get("rows") or [])[:max_rows]
    state[LAST_TABLE] = stored

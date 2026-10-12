"""Registro de herramientas que el LLM puede usar.

Cada dominio (turnos, vacaciones, nóminas…) expone herramientas tipadas.
El modelo decide cuál usar y con qué parámetros; la ejecución es código
determinista, validado y auditado.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ValidationError

from mia.auth import Permission, UserContext
from mia.diagnostics import EventStage, EventStatus, current_trace
from mia.diagnostics.trace import _current_call_id as _diag_call_id
from mia.llm import ToolCall, ToolSchema
from mia.observability import get_logger

log = get_logger(__name__)

# Diagnóstico de incidencias (ver _run()): tipo/ubicación (nunca el mensaje) de la última excepción
# real capturada en ESTA tarea async — execute() lo lee justo después de llamar a _run() y lo añade
# a su único evento TOOL_CALL_ERROR, nunca como un segundo evento duplicado.
_diag_last_exception: ContextVar[dict[str, Any] | None] = ContextVar("_diag_last_exception", default=None)


def _mia_frame_location(exc: BaseException) -> str | None:
    """Archivo:línea del último frame DENTRO de ``src/mia/`` en la pila de la excepción — nunca de una
    librería externa, y nunca el mensaje de la excepción (que podría contener datos sensibles)."""
    tb = exc.__traceback__
    last_mia_frame = None
    while tb is not None:
        filename = tb.tb_frame.f_code.co_filename.replace("\\", "/")
        if "/src/mia/" in filename or filename.startswith("src/mia/"):
            last_mia_frame = tb
        tb = tb.tb_next
    if last_mia_frame is None:
        return None
    filename = last_mia_frame.tb_frame.f_code.co_filename.replace("\\", "/")
    idx = filename.find("/src/")
    return f"{filename[idx + 1 :] if idx >= 0 else filename}:{last_mia_frame.tb_lineno}"


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
    attachment_service: Any | None = None
    """AttachmentService inyectado cuando la funcionalidad está activa."""


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


DEFAULT_MODULE = "rrhh"
"""Módulo al que se asigna una herramienta registrada sin indicar otro explícitamente — hoy
todas lo son. El único módulo que de verdad importa que se declare aparte es uno sin
herramientas reales todavía (ver mia.modules.finanzas): nada que filtrar, nada que romper."""


class ToolRegistry:
    def __init__(self, pending_domains: tuple[str, ...] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        self._module_of: dict[str, str] = {}
        self.pending_domains = pending_domains
        """Dominios que mIA todavía no puede consultar (se declaran para que no los prometa)."""

    def register(self, tool: Tool, *, module: str = DEFAULT_MODULE) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Herramienta duplicada: {tool.name}")
        self._tools[tool.name] = tool
        self._module_of[tool.name] = module

    def names(self) -> list[str]:
        return sorted(self._tools)

    def capabilities_for(self, user: UserContext) -> str:
        """Estado real de capacidades, calculado en código: el modelo no lo deduce.

        Deliberadamente NO filtra por módulo de la pregunta: es parte del prompt de sistema,
        fijo entre preguntas para que la caché de prompt no se rompa (ver conversation/engine.py).
        El filtro por módulo vive en schemas_for(), que sí varía por turno.
        """
        tools = [t for t in self._tools.values() if user.has(t.permission)]
        lines = ["Herramientas disponibles ahora (esta lista es completa):"]
        lines += [f"- {t.name}: {t.description.split('. ')[0]}" for t in tools] or ["- ninguna"]
        if self.pending_domains:
            lines.append("Dominios que TODAVÍA NO puedes consultar: " + ", ".join(self.pending_domains) + ".")
        return "\n".join(lines)

    def schemas_for(self, user: UserContext, *, modules: set[str] | None = None) -> list[ToolSchema]:
        """Solo las herramientas que el usuario puede usar y, si se indica, de esos módulos
        (el orquestador decide cuáles necesita la pregunta de este turno; mia.modules.finanzas
        hoy no aporta ninguna, así que por ahora esto nunca reduce lo que ya se ofrecía)."""
        return [
            tool.schema()
            for tool in self._tools.values()
            if user.has(tool.permission) and (modules is None or self._module_of.get(tool.name) in modules)
        ]

    async def execute(self, call: ToolCall, ctx: ToolContext) -> ToolExecution:
        started = time.perf_counter()
        tool = self._tools.get(call.name)
        trace = current_trace()

        try:
            args = json.loads(call.arguments or "{}")
        except json.JSONDecodeError:
            args = {}

        # Recopilar información de origen de la herramienta para el grafo de llamadas
        source_file: str | None = None
        source_module: str | None = None
        source_function: str | None = None
        if tool is not None:
            source_module = getattr(tool.handler, "__module__", None)
            source_function = getattr(tool.handler, "__qualname__", None)
            try:
                raw_path = inspect.getfile(tool.handler)
                # Normalizar a ruta relativa desde src/
                raw_path = raw_path.replace("\\", "/")
                idx = raw_path.find("/src/")
                source_file = raw_path[idx + 1:] if idx >= 0 else os.path.basename(raw_path)
            except (TypeError, OSError):
                pass

        if trace is not None:
            trace.emit(EventStage.TOOL_CALL_START, data={
                "tool": call.name,
                "args": args,
                "call_id": call.call_id,
                "source_file": source_file,
                "source_module": source_module,
                "source_function": source_function,
            })

        # Fijar el call_id en el ContextVar para que el código de dominio pueda linkear nodos SQL
        _call_id_token = _diag_call_id.set(call.call_id) if trace is not None else None
        _exc_token = _diag_last_exception.set(None)
        try:
            result = await self._run(tool, call, ctx)
            exception_info = _diag_last_exception.get()
        finally:
            if _call_id_token is not None:
                _diag_call_id.reset(_call_id_token)
            _diag_last_exception.reset(_exc_token)

        elapsed = int((time.perf_counter() - started) * 1000)
        is_error = result.status.value in ("error", "source_unavailable", "permission_denied")

        if trace is not None:
            event_data: dict[str, Any] = {"tool": call.name, "status": result.status.value}
            if exception_info:
                event_data.update(exception_info)
            trace.emit(
                EventStage.TOOL_CALL_ERROR if is_error else EventStage.TOOL_CALL_COMPLETE,
                status=EventStatus.ERROR if is_error else EventStatus.SUCCESS,
                duration_ms=elapsed,
                data=event_data,
            )
            # Añadir nodo al grafo de ejecución
            args_preview = ", ".join(
                f"{k}={v}" for k, v in args.items() if v is not None and v is not False
            )[:100]
            trace.add_call_graph_node({
                "id": f"tool:{call.name}:{call.call_id}",
                "kind": "tool_call",
                "label": f"{call.name}({args_preview})" if args_preview else call.name,
                "file": source_file,
                "module": source_module,
                "function": source_function,
                "args": args,
                "call_id": call.call_id,
                "duration_ms": elapsed,
                "status": "error" if is_error else "ok",
                "parent_id": "engine:root",
            })

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
        except Exception as exc:
            log.exception("tool.failed", tool=tool.name)
            # Diagnóstico de incidencias (trace mia-20261012-115403-bad97707): el mensaje/traceback
            # REAL ya iba a `log.exception` (server-side), pero nunca a la traza de diagnóstico —
            # para reconstruir una incidencia había que reproducirla a ciegas. Se guarda aquí solo el
            # TIPO de excepción y su ubicación (archivo:línea del propio código de mIA, nunca de
            # librerías externas) para que `execute()` lo añada a SU ÚNICO evento TOOL_CALL_ERROR
            # (nunca un segundo evento duplicado) — nunca el mensaje ni ningún argumento, que podrían
            # contener datos sensibles (importes, nombres…) que sí pueden aparecer en ``str(exc)``.
            _diag_last_exception.set(
                {"exception_type": type(exc).__name__, "exception_location": _mia_frame_location(exc)}
            )
            return ToolResult(ToolStatus.ERROR, "Error técnico al consultar la fuente de datos")


LAST_TABLE = "ultima_presentacion"


def remember_table(
    state: dict[str, Any],
    presentation: dict[str, Any] | None,
    max_rows: int,
    summary: Any = None,
    *,
    source_tool: str | None = None,
) -> None:
    """Guarda el último resultado mostrado (tabla, panel, ficha 360…) para convertirlo en informe.

    ``source_tool`` (revisión de la Fase F, "procedencia del análisis económico"): el nombre de la
    herramienta que REALMENTE produjo esta tabla concreta — se guarda junto a ella (``__source_tool__``)
    para que una validación posterior (p. ej. el guard de ``generar_informe``) se ate a la EJECUCIÓN que
    produjo lo que se va a exportar, nunca a "la última herramienta llamada en el turno" (``LAST_CALL``),
    que puede haber cambiado por una herramienta auxiliar posterior sin presentación propia (sin tocar
    esta tabla) — eso rechazaría un informe legítimo por una causa ajena a sus datos."""
    if not presentation or presentation.get("type") in {None, "download"}:
        return
    stored = dict(presentation)
    if stored.get("type") == "table":
        stored["rows"] = list(stored.get("rows") or [])[:max_rows]
    for sub_table in stored.get("tables") or []:
        sub_table["rows"] = list(sub_table.get("rows") or [])[:max_rows]
    if isinstance(summary, dict):
        stored["__summary__"] = dict(summary)
    if source_tool:
        stored["__source_tool__"] = source_tool
    state[LAST_TABLE] = stored


HISTORY = "historial_poblaciones"
MAX_HISTORY = 6


def remember_population(state: dict[str, Any], population: dict[str, Any] | None) -> None:
    """Guarda las últimas poblaciones (personas de cada resultado) para poder cruzarlas entre sí."""
    if not population:
        return
    history = [p for p in state.get(HISTORY, []) if p.get("etiqueta") != population.get("etiqueta")]
    state[HISTORY] = [*history, population][-MAX_HISTORY:]


LAST_CALL = "ultima_llamada"
_META_PARAMS = {"sobre_resultado_anterior", "resultado"}
"""Son instrucciones sobre CÓMO interpretar la pregunta, no un dato de negocio que repetir."""
_MAX_PARAM_VALUE_CHARS = 80


def remember_last_call(state: dict[str, Any], execution: ToolExecution) -> None:
    """Guarda la última herramienta que respondió bien, con los parámetros tal como los puso
    el modelo (no el resultado).

    No hay regex que cubra «y los de Cocina», «y en agosto», «y solo los de baja»… — son
    infinitas las formas de pedir «la misma pregunta, cambiando un dato». En vez de intentar
    enumerarlas, se le da al modelo la llamada estructurada para que decida él qué cambia,
    algo para lo que un LLM es bueno y una lista de patrones de texto nunca lo será del todo.
    """
    if execution.result.status is not ToolStatus.OK:
        return
    try:
        args: dict[str, Any] = json.loads(execution.call.arguments or "{}")
    except json.JSONDecodeError:
        args = {}
    params = {
        k: (v[:_MAX_PARAM_VALUE_CHARS] if isinstance(v, str) else v)
        for k, v in args.items()
        if k not in _META_PARAMS and v is not None and v is not False and v not in ("", [])
    }
    state[LAST_CALL] = {"herramienta": execution.call.name, "parametros": params}

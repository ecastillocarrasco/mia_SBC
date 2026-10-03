from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from mia.auth import Permission, UserContext
from mia.conversation import Tool, ToolContext, ToolRegistry, ToolResult, ToolStatus
from mia.conversation.tools import LAST_CALL, remember_last_call
from mia.llm import ToolCall


class Params(BaseModel):
    dias: int = Field(ge=1, le=31)


class ConParametrosVarios(BaseModel):
    departamento: str = ""
    incluir_inactivos: bool = False
    sobre_resultado_anterior: bool = False
    resultado: str | None = None
    limite: int = 0


async def _ok(params: Params, ctx: ToolContext) -> ToolResult:
    return ToolResult.ok({"dias": params.dias}, foco_periodo=params.dias)


async def _ok_varios(params: ConParametrosVarios, ctx: ToolContext) -> ToolResult:
    return ToolResult.ok({})


async def _not_found(params: Params, ctx: ToolContext) -> ToolResult:
    return ToolResult(ToolStatus.NOT_FOUND, "nadie encaja")


async def _slow(params: Params, ctx: ToolContext) -> ToolResult:
    await asyncio.sleep(1)
    return ToolResult.ok({})


async def _boom(params: Params, ctx: ToolContext) -> ToolResult:
    raise RuntimeError("SharePoint caído")


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(Tool("publica", "sin permiso", Params, _ok))
    registry.register(Tool("nominas", "con permiso", Params, _ok, permission=Permission.NOMINAS_LEER))
    registry.register(Tool("lenta", "timeout", Params, _slow, timeout_seconds=0.05))
    registry.register(Tool("rota", "falla", Params, _boom))
    registry.register(Tool("varios", "params variados", ConParametrosVarios, _ok_varios))
    registry.register(Tool("sin_suerte", "no encuentra nada", Params, _not_found))
    return registry


def _ctx(*roles: str) -> ToolContext:
    user = UserContext("u1", "Usuario", roles=frozenset(roles))
    return ToolContext(user=user, request_id=None, now=datetime.now(UTC))


def test_llm_only_sees_permitted_tools() -> None:
    registry = _registry()
    assert "nominas" not in [t.name for t in registry.schemas_for(_ctx("mia.responsable").user)]
    assert "nominas" in [t.name for t in registry.schemas_for(_ctx("mia.rrhh").user)]


async def test_permission_is_enforced_at_execution() -> None:
    execution = await _registry().execute(ToolCall("c", "nominas", '{"dias": 3}'), _ctx("mia.responsable"))
    assert execution.result.status is ToolStatus.PERMISSION_DENIED


async def test_invalid_arguments_are_reported_to_the_model() -> None:
    execution = await _registry().execute(ToolCall("c", "publica", '{"dias": 99}'), _ctx())
    assert execution.result.status is ToolStatus.INVALID_ARGUMENTS
    assert execution.result.summary[0]["campo"] == "dias"


async def test_timeout_is_source_unavailable_not_zero() -> None:
    execution = await _registry().execute(ToolCall("c", "lenta", '{"dias": 1}'), _ctx())
    assert execution.result.status is ToolStatus.SOURCE_UNAVAILABLE


async def test_handler_exception_is_contained() -> None:
    execution = await _registry().execute(ToolCall("c", "rota", '{"dias": 1}'), _ctx())
    assert execution.result.status is ToolStatus.ERROR
    assert "SharePoint" not in str(execution.result.summary)


async def test_parallel_execution_and_state_updates() -> None:
    calls = [ToolCall("a", "publica", '{"dias": 2}'), ToolCall("b", "publica", '{"dias": 5}')]
    executions = await _registry().execute_all(calls, _ctx())
    assert [e.result.summary["dias"] for e in executions] == [2, 5]
    assert executions[0].result.state_updates == {"foco_periodo": 2}


# ------------------------------------------------------------------ remember_last_call
async def test_remember_last_call_keeps_tool_and_params() -> None:
    execution = await _registry().execute(ToolCall("c", "publica", '{"dias": 5}'), _ctx())
    state: dict[str, object] = {}
    remember_last_call(state, execution)
    assert state[LAST_CALL] == {"herramienta": "publica", "parametros": {"dias": 5}}


async def test_remember_last_call_filters_meta_and_empty_params() -> None:
    """sobre_resultado_anterior/resultado son instrucciones de interpretación, no datos a repetir;
    los vacíos/False (los que dejó por defecto el modelo) tampoco aportan nada que repetir."""
    arguments = (
        '{"departamento": "Pisos", "incluir_inactivos": false, '
        '"sobre_resultado_anterior": true, "resultado": "baja", "limite": 0}'
    )
    execution = await _registry().execute(ToolCall("c", "varios", arguments), _ctx())
    state: dict[str, object] = {}
    remember_last_call(state, execution)
    assert state[LAST_CALL] == {"herramienta": "varios", "parametros": {"departamento": "Pisos", "limite": 0}}


async def test_remember_last_call_ignores_unsuccessful_calls() -> None:
    execution = await _registry().execute(ToolCall("c", "sin_suerte", '{"dias": 1}'), _ctx())
    state: dict[str, object] = {}
    remember_last_call(state, execution)
    assert LAST_CALL not in state


def test_duplicate_tool_names_are_rejected() -> None:
    registry = _registry()
    try:
        registry.register(Tool("publica", "otra", Params, _ok))
    except ValueError:
        return
    raise AssertionError("debería rechazar duplicados")

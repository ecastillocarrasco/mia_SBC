"""Tests del orquestador multi-módulo y el filtrado por módulo en ToolRegistry."""

from __future__ import annotations

from pydantic import BaseModel

from mia.auth import UserContext
from mia.conversation import Tool, ToolContext, ToolRegistry, ToolResult
from mia.conversation.orchestrator import select_modules
from mia.conversation.tools import DEFAULT_MODULE
from mia.modules.finanzas import KEYWORDS as FINANZAS_KEYWORDS

MODULE_KEYWORDS: dict[str, tuple[str, ...]] = {"finanzas": FINANZAS_KEYWORDS}


class Params(BaseModel):
    pass


async def _ok(params: Params, ctx: ToolContext) -> ToolResult:
    return ToolResult.ok({})


def _user() -> UserContext:
    return UserContext("u1", "Usuario", roles=frozenset())


# ------------------------------------------------------------------ select_modules


def test_default_module_always_present() -> None:
    result = select_modules("cuántos empleados hay hoy", MODULE_KEYWORDS)
    assert DEFAULT_MODULE in result


def test_finanzas_keyword_adds_finanzas_module() -> None:
    result = select_modules("muéstrame las facturas del mes", MODULE_KEYWORDS)
    assert "finanzas" in result
    assert DEFAULT_MODULE in result


def test_finanzas_module_added_on_partial_match() -> None:
    result = select_modules("tengo una pregunta sobre el presupuesto anual", MODULE_KEYWORDS)
    assert "finanzas" in result


def test_finanzas_module_not_added_without_keywords() -> None:
    result = select_modules("qué turnos tiene Ana mañana", MODULE_KEYWORDS)
    assert "finanzas" not in result
    assert DEFAULT_MODULE in result


def test_keyword_matching_is_case_insensitive() -> None:
    result = select_modules("¿Tienes info de FACTURACIÓN?", MODULE_KEYWORDS)
    assert "finanzas" in result


def test_empty_keywords_dict_returns_only_default() -> None:
    result = select_modules("facturas proveedores balance", {})
    assert result == {DEFAULT_MODULE}


# ------------------------------------------------------------------ ToolRegistry module filtering


def _registry_with_modules() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(Tool("herramienta_rrhh", "del módulo rrhh", Params, _ok), module="rrhh")
    registry.register(Tool("herramienta_finanzas", "del módulo finanzas", Params, _ok), module="finanzas")
    registry.register(Tool("herramienta_default", "sin módulo explícito", Params, _ok))
    return registry


def test_schemas_for_with_no_module_filter_returns_all() -> None:
    registry = _registry_with_modules()
    names = [t.name for t in registry.schemas_for(_user())]
    assert "herramienta_rrhh" in names
    assert "herramienta_finanzas" in names
    assert "herramienta_default" in names


def test_schemas_for_filters_by_module() -> None:
    registry = _registry_with_modules()
    names = [t.name for t in registry.schemas_for(_user(), modules={"rrhh"})]
    assert "herramienta_rrhh" in names
    assert "herramienta_default" in names  # DEFAULT_MODULE = "rrhh"
    assert "herramienta_finanzas" not in names


def test_schemas_for_finanzas_module_only() -> None:
    registry = _registry_with_modules()
    names = [t.name for t in registry.schemas_for(_user(), modules={"finanzas"})]
    assert "herramienta_finanzas" in names
    assert "herramienta_rrhh" not in names
    assert "herramienta_default" not in names


def test_schemas_for_multi_module_union() -> None:
    registry = _registry_with_modules()
    names = [t.name for t in registry.schemas_for(_user(), modules={"rrhh", "finanzas"})]
    assert "herramienta_rrhh" in names
    assert "herramienta_finanzas" in names
    assert "herramienta_default" in names

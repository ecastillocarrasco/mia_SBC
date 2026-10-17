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


def test_empty_keywords_dict_returns_only_always_on() -> None:
    """``empleados`` se incluye siempre (decisión explícita): resolver "la ficha de Juan" no
    lleva vocabulario de ningún dominio, así que no puede depender de que algo haya coincidido."""
    result = select_modules("facturas proveedores balance", {})
    assert result == {DEFAULT_MODULE, "empleados"}


# ------------------------------------------------------------------ fallback "nada coincidió -> todo"
# (CLAUDE.md: un hueco de vocabulario nunca debe quitarle una herramienta al modelo)

_REAL_MODULE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "turnos": ("turno", "turnos", "horario"),
    "nominas": ("nomina", "nominas", "salario"),
    "vacaciones": ("vacaciones", "saldo de vacaciones"),
    "finanzas": FINANZAS_KEYWORDS,
}


def test_matched_domain_excludes_the_rest() -> None:
    """El ahorro real: si se reconoce un dominio, NO se traen los demás dominios reales."""
    result = select_modules("qué turno tiene Ana hoy", _REAL_MODULE_KEYWORDS)
    assert result == {DEFAULT_MODULE, "empleados", "turnos"}


def test_multiple_matched_domains_are_both_included() -> None:
    result = select_modules("el saldo de vacaciones y la nomina de Ana", _REAL_MODULE_KEYWORDS)
    assert result == {DEFAULT_MODULE, "empleados", "vacaciones", "nominas"}


def test_unrecognized_message_falls_back_to_every_real_domain() -> None:
    """Nada coincide (vocabulario incompleto o pregunta atípica): catálogo completo de dominios
    reales, igual que si no se filtrara nada — nunca se queda sin una herramienta por esto."""
    result = select_modules("esto no se parece a ningún vocabulario conocido", _REAL_MODULE_KEYWORDS)
    assert result == {DEFAULT_MODULE, "empleados", "turnos", "nominas", "vacaciones"}


def test_only_finanzas_matching_does_not_pull_in_every_rrhh_domain() -> None:
    """Finanzas no tiene herramientas reales: que coincida no debe arrastrar los 82 de RRHH."""
    result = select_modules("muéstrame las facturas del mes", _REAL_MODULE_KEYWORDS)
    assert result == {DEFAULT_MODULE, "empleados", "finanzas"}


def test_natural_language_variation_for_nominas() -> None:
    """Varias formulaciones distintas para el mismo dominio (CLAUDE.md: tolerar variación de
    lenguaje natural, no solo la frase canónica)."""
    for message in ("cuánto cobra Ana este mes", "sueldo de Ana en agosto", "las nóminas de Ana"):
        result = select_modules(message, _REAL_MODULE_KEYWORDS)
        assert "nominas" in result, message


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

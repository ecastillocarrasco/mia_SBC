"""Módulo Finanzas — sin fuente de datos real todavía.

Se incorpora junto con el orquestador multi-módulo (`conversation/orchestrator.py`) para que
el enrutado entre módulos se diseñe contra un segundo módulo real, no contra una interfaz
especulativa (el propio roadmap del proyecto avisa de no construir el orquestador sin esto).

No se inventan datos ni herramientas: ``register`` no da de alta ninguna. Cuando Sunset Beach
Club tenga una fuente de datos de Finanzas (lista de SharePoint, ERP…), este módulo gana sus
propios dominios con el mismo patrón que ``modules/rrhh`` — el orquestador no necesita cambiar.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mia.modules import ModuleManifest

if TYPE_CHECKING:
    from mia.conversation.tools import ToolRegistry

MANIFEST = ModuleManifest(
    name="finanzas",
    description="Finanzas: facturación, contabilidad, presupuestos, tesorería. Sin fuente de "
    "datos conectada todavía.",
    permissions=(),
    languages=("es",),
    sources=(),
)

KEYWORDS = (
    "factura",
    "facturas",
    "facturacion",
    "facturación",
    "contabilidad",
    "presupuesto",
    "presupuestos",
    "tesoreria",
    "tesorería",
    "balance",
    "finanzas",
    "financiero",
    "financiera",
    "proveedor",
    "proveedores",
)
"""Vocabulario para que el orquestador reconozca una pregunta de este módulo (CLAUDE.md pide
enrutado determinista; no es una lista exhaustiva, es la que decide si avisar de que el módulo
no está disponible en vez de dejar que el modelo invente datos de Finanzas)."""


def register(registry: ToolRegistry, deps: Any) -> None:
    """Sin fuente de datos real todavía: no registra ninguna herramienta (ver docs/pendientes.md)."""
    return

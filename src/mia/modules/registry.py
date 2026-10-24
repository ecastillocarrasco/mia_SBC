"""Ensamblado de dominios de mIA en un único registro de herramientas."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mia.data import Database

if TYPE_CHECKING:
    from mia.conversation import ToolRegistry


def build_registry(
    db: Database,
    stale_after_minutes: int = 30,
    *,
    settings: Any = None,
    llm: Any = None,
    graph: Any = None,
    sharepoint: Any = None,
    report_storage: Any = None,
    enabled: list[str] | None = None,
) -> ToolRegistry:
    """Compone dominios hermanos, sin hacer que uno sea dueño de otro.

    RRHH conserva su registro especializado; el correo se registra aquí como paquete autónomo.
    """
    from mia.modules.correo import register as register_mail
    from mia.modules.correo.deps import MailDeps
    from mia.modules.rrhh import build_rrhh_registry

    hr_enabled = None if enabled is None else [domain for domain in enabled if domain != "correo"]
    registry = build_rrhh_registry(
        db,
        stale_after_minutes,
        settings=settings,
        llm=llm,
        graph=graph,
        sharepoint=sharepoint,
        report_storage=report_storage,
        enabled=hr_enabled,
    )
    if enabled is None or "correo" in enabled:
        with registry.using_module("correo"):
            register_mail(registry, MailDeps(settings=settings, graph=graph, db=db))
    else:
        registry.pending_domains = (*registry.pending_domains, "correo personal")
    return registry

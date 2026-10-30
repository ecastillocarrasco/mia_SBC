"""Dominio de correo corporativo, independiente de RRHH."""

from mia.conversation import ToolRegistry
from mia.modules.correo.deps import MailDeps
from mia.modules.correo.manifest import MANIFEST
from mia.modules.correo.tools import KEYWORDS
from mia.modules.correo.tools import register as register_mail


def register(registry: ToolRegistry, deps: MailDeps) -> None:
    register_mail(registry, deps)
    config = getattr(getattr(deps.settings, "mail", None), "calendar", None)
    if config is not None and config.enabled:
        from mia.modules.correo.calendar.tools import register as register_calendar  # noqa: PLC0415

        register_calendar(registry, deps)


__all__ = ["KEYWORDS", "MANIFEST", "register"]

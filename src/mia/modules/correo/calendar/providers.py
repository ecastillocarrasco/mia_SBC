"""Único punto de selección del proveedor; no hay fallback entre cuentas."""

from collections.abc import Callable

from mia.modules.correo.calendar.microsoft365 import Microsoft365CalendarProvider
from mia.modules.correo.calendar.models import CalendarProvider
from mia.modules.correo.deps import MailDeps

PROVIDERS: dict[str, Callable[[MailDeps], CalendarProvider | None]] = {
    "microsoft365": lambda deps: Microsoft365CalendarProvider(deps.graph) if deps.graph is not None else None,
}


def build_provider(deps: MailDeps) -> CalendarProvider | None:
    factory = PROVIDERS.get(deps.settings.mail.calendar.default_provider)
    return factory(deps) if factory is not None else None

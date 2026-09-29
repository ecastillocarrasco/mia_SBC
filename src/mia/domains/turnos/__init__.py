from mia.conversation import ToolRegistry
from mia.domains.common import Deps
from mia.domains.turnos import historico
from mia.domains.turnos.periods import ABSENCE_KINDS, AbsencePeriod, absence_periods
from mia.domains.turnos.tools import register as _register_tools

__all__ = ["ABSENCE_KINDS", "AbsencePeriod", "absence_periods", "register"]


def register(registry: ToolRegistry, deps: Deps) -> None:
    _register_tools(registry, deps)
    historico.register(registry, deps)
    from mia.domains.turnos.companeros import companeros_de_turno  # noqa: PLC0415

    registry.register(companeros_de_turno(deps))

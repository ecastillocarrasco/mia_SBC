from mia.conversation import ToolRegistry
from mia.modules.rrhh.common import Deps
from mia.modules.rrhh.turnos import historico
from mia.modules.rrhh.turnos.periods import ABSENCE_KINDS, AbsencePeriod, absence_periods
from mia.modules.rrhh.turnos.tools import KEYWORDS
from mia.modules.rrhh.turnos.tools import register as _register_tools

__all__ = ["ABSENCE_KINDS", "KEYWORDS", "AbsencePeriod", "absence_periods", "register"]


def register(registry: ToolRegistry, deps: Deps) -> None:
    _register_tools(registry, deps)
    historico.register(registry, deps)
    from mia.modules.rrhh.turnos.companeros import companeros_de_turno  # noqa: PLC0415

    registry.register(companeros_de_turno(deps))

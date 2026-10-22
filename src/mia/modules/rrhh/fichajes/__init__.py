from mia.conversation import ToolRegistry
from mia.modules.rrhh.common import Deps
from mia.modules.rrhh.fichajes import informe, tools
from mia.modules.rrhh.fichajes.tools import KEYWORDS as _TOOLS_KEYWORDS

KEYWORDS = _TOOLS_KEYWORDS + informe.KEYWORDS


def register(registry: ToolRegistry, deps: Deps) -> None:
    tools.register(registry, deps)
    informe.register(registry, deps)


__all__ = ["KEYWORDS", "register"]

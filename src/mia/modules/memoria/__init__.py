"""Módulo Memoria: Memoria Inteligente V1, recuerdos manuales por usuario.

Transversal y abierto a cualquier rol de permisos (como ``community``), pero personal: cada
usuario solo ve y gestiona sus propios recuerdos (``Permission.MEMORIA_USAR``, concedida en
``_UNIVERSAL_CON_ROL`` igual que Correo/Noticias). Interruptor global en
``Settings.memory.enabled`` (``MIA_MEMORY__ENABLED``, por defecto ``False``): con él apagado,
``register()`` no da de alta ninguna herramienta y no existe endpoint ni control visual.

Alcance reducido deliberado — ver ``src/mia/modules/memoria/tools.py`` para el detalle y los
límites de esta primera versión (sin resumen automático de conversaciones ni búsqueda semántica).
"""

from __future__ import annotations

from mia.modules import ModuleManifest
from mia.modules.memoria.tools import KEYWORDS, register

MANIFEST = ModuleManifest(
    name="memoria",
    description="Memoria Inteligente V1: recuerdos manuales por usuario, guardados solo cuando "
    "el usuario lo pide expresamente, recuperados entre conversaciones, sesiones y mundos.",
    permissions=("memoria:usar",),
    languages=("es",),
    sources=(),
)

__all__ = ["KEYWORDS", "MANIFEST", "register"]

"""Módulo Community: funcionalidades transversales abiertas a cualquier rol de permisos.

Un dominio más junto a ``rrhh``, ``finanzas`` e ``it`` (mismo nivel), pero sin restricción de
rol: cada dominio bajo ``DOMAINS`` es información o utilidades que debe poder usar cualquier
persona autenticada, sea cual sea su ``Permission``. Empieza con ``noticias`` (prensa externa
sobre Sunset Beach Club / Grupo FBD) y ``newsletter`` (comunicación interna sincronizada desde
SharePoint); más funcionalidades de Community se añadirán como nuevos paquetes hermanos, cada
uno con su propio ``register()``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mia.data import Database
from mia.modules import ModuleManifest
from mia.modules.community import newsletter, noticias
from mia.modules.community.common import Deps

if TYPE_CHECKING:
    from mia.conversation.tools import ToolRegistry

MANIFEST = ModuleManifest(
    name="community",
    description="Community: funcionalidades transversales abiertas a todos los roles — "
    "noticias corporativas y de grupo (Sunset Beach Club / Grupo FBD) y la newsletter interna.",
    permissions=(),
    languages=("es", "en"),
    sources=(
        "rss:google_news_sunset_beach_club",
        "rss:google_news_fbd_hotels",
        "rss:google_news_farmer_business_developments",
        "web:farmerbusinessdevelopments_investor_news",
        "sharepoint:NewsletterCorporativa",
    ),
)

DOMAINS: dict[str, str] = {
    "noticias": "noticias corporativas y de grupo (prensa externa)",
    "newsletter": "newsletter corporativa interna",
}
"""Solo a título descriptivo (qué hay bajo Community); el registro real vive en ``register()``,
explícito en vez de genérico porque cada dominio nuevo puede necesitar su propia configuración."""


def register(registry: ToolRegistry, settings: Any, db: Database) -> None:
    with registry.using_module("noticias"):
        noticias.register(registry, enabled=settings.noticias.enabled)
    with registry.using_module("newsletter"):
        newsletter.register(registry, Deps(db=db))


__all__ = ["DOMAINS", "MANIFEST", "register"]

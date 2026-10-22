"""Newsletter corporativa interna (lista «NewsletterCorporativa» de SharePoint, sincronizada).

Distinta de ``community.noticias`` (prensa externa sobre Sunset Beach Club / Grupo FBD): esto es
la comunicación interna que RRHH publica y mantiene a mano (jubilaciones, campañas, avisos…), ya
curada y categorizada por la propia organización — no hace falta clasificarla por palabra clave
como la prensa externa, su «Categoria» de SharePoint ya es la categoría real.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from mia.conversation import Tool, ToolContext, ToolRegistry, ToolResult, ToolStatus
from mia.data import NewsletterItem
from mia.modules.community.common import Deps
from mia.text import normalize_key

KEYWORDS = (
    "newsletter", "newsletter corporativo", "boletin", "boletín", "boletin corporativo",
    "boletín corporativo", "comunicado interno", "comunicados internos", "circular interna",
    "circulares internas", "tablon de anuncios", "tablón de anuncios", "anuncios internos",
    "noticias internas", "noticia interna",
)
"""Vocabulario para el orquestador (`select_modules`). Deliberadamente sin «noticia»/«noticias»
sueltas (ver `community.noticias.KEYWORDS`): evita que cualquier «noticias» genérico arrastre
también esta herramienta cuando lo que se pide es prensa externa."""

MAX_LIMIT = 50
_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp")

_COMPANY_NAME_VARIANTS = frozenset({"sunset beach club", "sbc", "sunset beach"})
"""Esta newsletter es SIEMPRE la de Sunset Beach Club: no hay otra empresa de la que pudiera ser.
El modelo a veces convierte "newsletter de Sunset Beach Club" en un filtro de categoría literal
("categoria": "Sunset Beach Club") — como ninguna categoría real se llama así, eso vacía el
resultado por completo. Se descarta en código, no solo con texto de prompt, porque filtrar por el
propio nombre de la empresa nunca es una categoría real en este dominio."""


def _is_company_name_noise(categoria: str) -> bool:
    return normalize_key(categoria) in _COMPANY_NAME_VARIANTS


def _article_link(url: str | None) -> str | None:
    """«Enlace» a veces apunta a una imagen suelta (p. ej. una reutilizada de otra tarjeta del
    portal), no a un artículo — visto en datos reales. Mostrarla como «leer más» llevaría a una
    imagen sin contexto, así que se descarta en ese caso."""
    if not url or url.lower().split("?", 1)[0].endswith(_IMAGE_EXTENSIONS):
        return None
    return url


def _row(item: NewsletterItem) -> dict[str, Any]:
    category = item.category or None
    if item.featured and category:
        category = f"Destacada · {category}"
    elif item.featured:
        category = "Destacada"
    return {
        "titulo": item.title,
        "fuente": "Newsletter corporativo",
        "empresa": "Newsletter interno",
        "categoria": category,
        "fecha": item.created_at.strftime("%d/%m/%Y") if item.created_at else None,
        "resumen": item.summary,
        "cuerpo": item.body,
        "url": _article_link(item.link_url),
        "imagen": f"/api/community/newsletter/{item.sp_id}/imagen" if item.image_url else None,
    }


def _presentation(items: list[NewsletterItem]) -> dict[str, Any]:
    rows = [_row(i) for i in items]
    return {
        "type": "news_list",
        "title": "Newsletter corporativa",
        "columns": ["Título", "Categoría", "Fecha"],
        "rows": [[r["titulo"], r["categoria"], r["fecha"]] for r in rows],
        "news_rows": rows,
    }


class NewsletterParams(BaseModel):
    destacadas: bool = Field(
        default=False, description="true SOLO si el usuario pide expresamente lo destacado/lo más importante."
    )
    categoria: str | None = Field(
        default=None, description="Filtra por categoría SOLO si el usuario la pide explícitamente, en sus "
        "propias palabras (p. ej. «corporativa»). Vacío si no la pide. Esta newsletter YA es la de "
        "Sunset Beach Club (no hay otra empresa posible): si el usuario dice «de Sunset Beach Club» o "
        "«de SBC», eso no es una categoría, es solo nombrar de qué empresa es — deja este campo vacío."
    )
    limite: int = Field(default=15, ge=1, le=MAX_LIMIT)


def _sort_key(item: NewsletterItem) -> tuple[int, float]:
    order = item.order if item.order is not None else 10**9
    created = item.created_at.timestamp() if item.created_at else 0.0
    return (order, -created)


def newsletter_corporativo(deps: Deps) -> Tool:
    async def handler(p: NewsletterParams, ctx: ToolContext) -> ToolResult:
        today = ctx.now.date()
        async with deps.db.session() as db:
            stmt = select(NewsletterItem).where(
                NewsletterItem.active.is_(True),
                or_(NewsletterItem.expires_at.is_(None), NewsletterItem.expires_at >= today),
            )
            if p.destacadas:
                stmt = stmt.where(NewsletterItem.featured.is_(True))
            items = list((await db.scalars(stmt)).all())
            fresh = await deps.freshness(db, "newsletter_corporativa")
        if p.categoria and not _is_company_name_noise(p.categoria):
            wanted = normalize_key(p.categoria)
            items = [i for i in items if wanted in normalize_key(i.category or "")]
        items.sort(key=_sort_key)
        shown = items[: p.limite]
        if not shown:
            return ToolResult(ToolStatus.NOT_FOUND, "No hay noticias de la newsletter corporativa con ese filtro.")
        summary: dict[str, Any] = {
            "noticias_mostradas": len(shown),
            "noticias": [_row(i) for i in shown],
        }
        if not fresh.get("al_dia", True):
            summary["aviso"] = fresh.get("aviso")
        return ToolResult(ToolStatus.OK, summary, _presentation(shown))

    return Tool(
        "newsletter_corporativo",
        "Newsletter corporativa interna de Sunset Beach Club (comunicados, avisos y noticias que "
        "RRHH publica para la plantilla: jubilaciones, campañas, eventos internos…). Úsala para "
        "«newsletter», «boletín corporativo», «comunicados internos», «circular interna», «tablón "
        "de anuncios» o variantes similares. NO es prensa externa — para eso usa "
        "noticias_corporativas.",
        NewsletterParams,
        handler,
        permission=None,
        timeout_seconds=15.0,
    )


def register(registry: ToolRegistry, deps: Deps) -> None:
    registry.register(newsletter_corporativo(deps))


__all__ = ["KEYWORDS", "register"]

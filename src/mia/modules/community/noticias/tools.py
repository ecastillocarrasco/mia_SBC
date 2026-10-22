"""Herramienta conversacional de noticias corporativas y de grupo.

Información pública (prensa, comunicados a inversores): sin permiso asociado, igual que las
herramientas de ``sistema`` — cualquier usuario autenticado puede consultarla.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from mia.conversation import Tool, ToolContext, ToolResult, ToolStatus
from mia.modules.community.noticias.classify import CATEGORY_LABELS, match_category_query
from mia.modules.community.noticias.dedup import dedupe
from mia.modules.community.noticias.sources import GROUP_FBD, GROUP_SUNSET, NewsItem, fetch_all, new_client

GROUP_LABELS: dict[str, str] = {
    GROUP_SUNSET: "Sunset Beach Club",
    GROUP_FBD: "Grupo FBD (FBD Hotels & Resorts / Farmer Business Developments)",
}

KEYWORDS = (
    "noticia", "noticias", "prensa", "actualidad", "hemeroteca",
    "noticias de la empresa", "noticias corporativas", "noticias del grupo",
    "grupo fbd", "fbd hotels", "fbd hoteles", "farmer business developments",
    "sunset beach club noticias", "que se dice de", "qué se dice de",
)
"""Vocabulario para el orquestador (`select_modules`, CLAUDE.md pide enrutado determinista).
No es exhaustivo: si no coincide nada, el catálogo completo se ofrece igual (ver
`conversation/orchestrator.py`)."""

MAX_LIMIT = 50


def _news_rows(items: list[NewsItem]) -> list[dict[str, Any]]:
    return [
        {
            "titulo": item.titulo,
            "fuente": item.fuente,
            "empresa": GROUP_LABELS.get(item.grupo, item.grupo),
            "categoria": CATEGORY_LABELS.get(item.categoria, item.categoria),
            "fecha": item.publicado.strftime("%d/%m/%Y") if item.publicado else None,
            "resumen": item.resumen or None,
            "url": item.url,
        }
        for item in items
    ]


def _news_table(title: str, items: list[NewsItem]) -> dict[str, Any]:
    return {
        "type": "news_list",
        "title": title,
        "columns": ["Título", "Empresa", "Categoría", "Fuente", "Fecha"],
        "rows": [
            [i.titulo, GROUP_LABELS.get(i.grupo, i.grupo), CATEGORY_LABELS.get(i.categoria, i.categoria),
             i.fuente, i.publicado.strftime("%d/%m/%Y") if i.publicado else "—"]
            for i in items
        ],
        "news_rows": _news_rows(items),
    }


class NoticiasParams(BaseModel):
    empresa: Literal["todas", "sunset", "fbd_group"] = Field(
        default="todas",
        description="«sunset» para Sunset Beach Club, «fbd_group» para el Grupo FBD (FBD Hotels & "
        "Resorts / Farmer Business Developments), «todas» si no se especifica una empresa concreta.",
    )
    categoria: str | None = Field(
        default=None,
        description="Filtra por categoría temática SOLO si el usuario la pide explícitamente, en "
        "sus propias palabras (p. ej. «financiera», «inversión», «hotelera», «nombramientos», "
        "«premios»). Vacío si no la pide.",
    )
    limite: int = Field(default=15, ge=1, le=MAX_LIMIT)


def noticias_corporativas() -> Tool:
    async def handler(p: NoticiasParams, ctx: ToolContext) -> ToolResult:
        del ctx  # sin uso: la herramienta no depende de la sesión ni del usuario
        category_filter = match_category_query(p.categoria) if p.categoria else None
        async with new_client() as client:
            raw_items, failed_sources = await fetch_all(client)
        items = dedupe(raw_items)
        if p.empresa != "todas":
            items = [i for i in items if i.grupo == p.empresa]
        if category_filter:
            items = [i for i in items if i.categoria == category_filter]
        items.sort(key=lambda i: i.publicado or datetime.min.replace(tzinfo=UTC), reverse=True)
        shown = items[: p.limite]

        if not shown:
            if failed_sources and len(failed_sources) >= 4:  # las 4 fuentes configuradas
                return ToolResult(
                    ToolStatus.SOURCE_UNAVAILABLE,
                    "No se ha podido consultar ninguna fuente de noticias ahora mismo; inténtalo de nuevo "
                    "en unos minutos.",
                )
            return ToolResult(ToolStatus.NOT_FOUND, "No hay noticias que encajen con ese filtro ahora mismo.")

        summary: dict[str, Any] = {"noticias_mostradas": len(shown), "noticias": _news_rows(shown)}
        if failed_sources:
            summary["aviso"] = "No se ha podido consultar: " + ", ".join(failed_sources)
        return ToolResult(ToolStatus.OK, summary, _news_table("Noticias corporativas y del grupo", shown))

    return Tool(
        "noticias_corporativas",
        "Noticias recientes de Sunset Beach Club y del Grupo FBD (FBD Hotels & Resorts, Farmer "
        "Business Developments): prensa y comunicados a inversores, recogidos de varias fuentes, "
        "sin duplicados y clasificados por empresa y por tema (inversión/financiera, hotelera/"
        "turismo, nombramientos, premios, corporativo general). Úsala para «noticias de la "
        "empresa», «noticias del grupo», «qué se dice de Sunset Beach Club», «prensa de FBD "
        "Hotels», «actualidad de Farmer Business Developments» o variantes similares — no hace "
        "falta la frase exacta.",
        NoticiasParams,
        handler,
        permission=None,
        timeout_seconds=15.0,
    )


def register(registry: Any, *, enabled: bool = True) -> None:
    if not enabled:
        return
    registry.register(noticias_corporativas())

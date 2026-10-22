"""Newsletter corporativa interna (lista sincronizada «NewsletterCorporativa» de SharePoint)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from mia.auth import UserContext
from mia.conversation.tools import ToolContext, ToolStatus
from mia.data import NewsletterItem
from mia.modules.community.common import Deps
from mia.modules.community.newsletter.tools import newsletter_corporativo
from tests.dbutil import fresh_database

USER = UserContext("u1", "Enrique", roles=frozenset({"mia.admin"}))
TODAY = date(2026, 10, 21)
NOW = datetime(2026, 10, 21, 9, 0)


def _ctx() -> ToolContext:
    return ToolContext(user=USER, request_id="req-1", now=NOW, session_state={})


def _item(
    sp_id: int, title: str, *, category: str | None = "Corporativa", featured: bool = False,
    active: bool = True, order: int | None = None, expires_at: date | None = None,
    summary: str | None = "Resumen breve.", link_url: str | None = None, image_url: str | None = None,
    created_at: datetime | None = None,
) -> NewsletterItem:
    return NewsletterItem(
        sp_id=sp_id, title=title, summary=summary, body="Cuerpo completo de la noticia.",
        category=category, featured=featured, active=active, order=order, expires_at=expires_at,
        image_url=image_url, link_url=link_url, button_text="Consultar",
        created_at=created_at or datetime(2026, 10, 1), modified_at=created_at or datetime(2026, 10, 1),
    )


async def _seed(tmp_path: Path, rows: list[NewsletterItem]) -> Any:
    db = await fresh_database(tmp_path, "newsletter.db")
    async with db.session() as s:
        s.add_all(rows)
    return db


async def test_returns_only_active_non_expired_items_sorted_by_order(tmp_path: Path) -> None:
    db = await _seed(tmp_path, [
        _item(1, "Jubilación Blas", order=1),
        _item(2, "Semana Saludable", order=2),
        _item(3, "Inactiva", active=False, order=0),
        _item(4, "Caducada", order=0, expires_at=TODAY - timedelta(days=1)),
        _item(5, "Vigente hasta hoy", order=3, expires_at=TODAY),
    ])
    tool = newsletter_corporativo(Deps(db=db))
    result = await tool.handler(tool.params(), _ctx())

    assert result.status is ToolStatus.OK
    titles = [n["titulo"] for n in result.summary["noticias"]]
    assert titles == ["Jubilación Blas", "Semana Saludable", "Vigente hasta hoy"]
    await db.dispose()


async def test_destacadas_filters_to_featured_only(tmp_path: Path) -> None:
    db = await _seed(tmp_path, [
        _item(1, "Normal", order=1, featured=False),
        _item(2, "Importante", order=2, featured=True),
    ])
    tool = newsletter_corporativo(Deps(db=db))
    result = await tool.handler(tool.params(destacadas=True), _ctx())

    assert result.status is ToolStatus.OK
    assert result.summary["noticias_mostradas"] == 1
    assert result.summary["noticias"][0]["titulo"] == "Importante"
    assert result.summary["noticias"][0]["categoria"] == "Destacada · Corporativa"
    await db.dispose()


async def test_categoria_filter_is_natural_language_substring_match(tmp_path: Path) -> None:
    db = await _seed(tmp_path, [
        _item(1, "A", order=1, category="Corporativa"),
        _item(2, "B", order=2, category="Salud y bienestar"),
    ])
    tool = newsletter_corporativo(Deps(db=db))
    result = await tool.handler(tool.params(categoria="salud"), _ctx())

    assert result.status is ToolStatus.OK
    assert result.summary["noticias_mostradas"] == 1
    assert result.summary["noticias"][0]["titulo"] == "B"
    await db.dispose()


async def test_company_name_as_categoria_is_ignored_not_treated_as_a_filter(tmp_path: Path) -> None:
    """Regresión: "muéstrame las newsletter de Sunset Beach Club" hacía que el modelo pasara
    categoria="Sunset Beach Club"; como ninguna categoría real se llama así, el resultado quedaba
    vacío aunque hubiera newsletters activas. Esta newsletter ya es, por definición, la de Sunset
    Beach Club, así que mencionar la empresa no debe filtrar nada."""
    db = await _seed(tmp_path, [
        _item(1, "A", order=1, category="Corporativa"),
        _item(2, "B", order=2, category="General"),
    ])
    tool = newsletter_corporativo(Deps(db=db))
    for noise in ("Sunset Beach Club", "sbc", "SBC", "sunset beach club"):
        result = await tool.handler(tool.params(categoria=noise), _ctx())
        assert result.status is ToolStatus.OK, noise
        assert result.summary["noticias_mostradas"] == 2, noise
    await db.dispose()


async def test_not_found_when_nothing_matches(tmp_path: Path) -> None:
    db = await _seed(tmp_path, [_item(1, "Única", active=False)])
    tool = newsletter_corporativo(Deps(db=db))
    result = await tool.handler(tool.params(), _ctx())

    assert result.status is ToolStatus.NOT_FOUND
    await db.dispose()


async def test_presentation_reuses_the_news_list_card_panel(tmp_path: Path) -> None:
    db = await _seed(tmp_path, [_item(1, "Jubilación Blas", order=1, link_url="https://example.test/noticia")])
    tool = newsletter_corporativo(Deps(db=db))
    result = await tool.handler(tool.params(), _ctx())

    assert result.presentation is not None
    assert result.presentation["type"] == "news_list"
    row = result.presentation["news_rows"][0]
    assert row["titulo"] == "Jubilación Blas"
    assert row["fuente"] == "Newsletter corporativo"
    assert row["empresa"] == "Newsletter interno"  # distingue de las noticias externas de SBC
    assert row["url"] == "https://example.test/noticia"
    await db.dispose()


async def test_image_only_enlace_is_not_presented_as_a_read_more_link(tmp_path: Path) -> None:
    """Dato real: «Enlace» a veces apunta a una imagen suelta reutilizada de otra tarjeta del
    portal, no a un artículo — mostrarla como «leer más» llevaría a una imagen sin contexto."""
    db = await _seed(tmp_path, [
        _item(1, "Con imagen suelta", order=1, link_url="https://x.test/imagesNewsLetter/imgHomeTurnos.png"),
        _item(2, "Con enlace real", order=2, link_url="https://x.test/noticias/articulo"),
    ])
    tool = newsletter_corporativo(Deps(db=db))
    result = await tool.handler(tool.params(), _ctx())

    rows = {r["titulo"]: r for r in result.summary["noticias"]}
    assert rows["Con imagen suelta"]["url"] is None
    assert rows["Con enlace real"]["url"] == "https://x.test/noticias/articulo"
    await db.dispose()


async def test_presentation_carries_a_proxied_image_url_for_the_detail_popup(tmp_path: Path) -> None:
    """La URL de SharePoint se guarda, pero NUNCA se expone tal cual al navegador: responde 403 sin
    sesión ahí (verificado). La presentación debe llevar la ruta propia de mIA que la sirve con sus
    propias credenciales (``api.routes.community``), no la URL directa de SharePoint."""
    db = await _seed(tmp_path, [
        _item(1, "Jubilación Blas", order=1, image_url="https://x.test/images/blas.png"),
        _item(2, "Sin imagen", order=2, image_url=None),
    ])
    tool = newsletter_corporativo(Deps(db=db))
    result = await tool.handler(tool.params(), _ctx())

    rows = {r["titulo"]: r for r in result.presentation["news_rows"]}
    assert rows["Jubilación Blas"]["imagen"] == "/api/community/newsletter/1/imagen"
    assert rows["Sin imagen"]["imagen"] is None
    await db.dispose()


async def test_summary_includes_full_body_for_the_model_to_read(tmp_path: Path) -> None:
    db = await _seed(tmp_path, [_item(1, "Jubilación Blas", order=1)])
    tool = newsletter_corporativo(Deps(db=db))
    result = await tool.handler(tool.params(), _ctx())

    assert result.summary["noticias"][0]["cuerpo"] == "Cuerpo completo de la noticia."
    await db.dispose()


async def test_presentation_carries_the_body_for_the_detail_popup(tmp_path: Path) -> None:
    """Regresión: la presentación (lo que pinta el popup) se quedaba sin «cuerpo» — solo lo
    llevaba el resumen que ve el modelo, nunca lo que ve la pantalla."""
    db = await _seed(tmp_path, [_item(1, "Jubilación Blas", order=1)])
    tool = newsletter_corporativo(Deps(db=db))
    result = await tool.handler(tool.params(), _ctx())

    row = result.presentation["news_rows"][0]
    assert row["cuerpo"] == "Cuerpo completo de la noticia."
    assert row["resumen"] == "Resumen breve."
    await db.dispose()


def test_tool_has_no_permission_requirement() -> None:
    tool = newsletter_corporativo(Deps(db=None))  # type: ignore[arg-type]
    assert tool.permission is None

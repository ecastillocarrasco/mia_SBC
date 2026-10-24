"""Herramienta ``noticias_corporativas``: filtrado por empresa/categoría, orden, límite y
degradación cuando las fuentes externas no responden. ``fetch_all`` se sustituye por datos fijos
(ver ``tests/test_noticias_sources.py`` para el parsing real contra RSS/HTML)."""

from __future__ import annotations

from datetime import datetime

import pytest

import mia.modules.community.noticias.tools as noticias_tools
from mia.auth import Permission, UserContext
from mia.conversation.tools import ToolContext, ToolStatus
from mia.modules.community.noticias.sources import GROUP_FBD, GROUP_SUNSET, NewsItem
from mia.modules.community.noticias.tools import noticias_corporativas

USER = UserContext("u1", "Enrique", roles=frozenset({"mia.admin"}))


def _ctx() -> ToolContext:
    return ToolContext(user=USER, request_id="req-1", now=datetime(2026, 10, 20, 9, 0), session_state={})


def _item(titulo: str, grupo: str, categoria: str, dia: int, url: str | None = None) -> NewsItem:
    return NewsItem(
        titulo=titulo, url=url or f"https://example.test/{titulo}", fuente="Fuente",
        grupo=grupo, categoria=categoria, publicado=datetime(2026, 10, dia),
    )


FIXTURE_ITEMS = [
    _item("Sunset abre temporada", GROUP_SUNSET, "hotelera_turismo", 10),
    _item("FBD publica informe anual", GROUP_FBD, "inversion_financiera", 15),
    _item("FBD Hotels gana premio", GROUP_FBD, "premios_reconocimientos", 18),
]


@pytest.fixture(autouse=True)
def _patch_fetch_all(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch_all(client: object) -> tuple[list[NewsItem], list[str]]:
        del client
        return list(FIXTURE_ITEMS), []

    monkeypatch.setattr(noticias_tools, "fetch_all", fake_fetch_all)


async def test_returns_all_news_sorted_by_date_desc() -> None:
    tool = noticias_corporativas()
    result = await tool.handler(tool.params(), _ctx())

    assert result.status is ToolStatus.OK
    titles = [n["titulo"] for n in result.summary["noticias"]]
    assert titles == ["FBD Hotels gana premio", "FBD publica informe anual", "Sunset abre temporada"]


async def test_filters_by_empresa() -> None:
    tool = noticias_corporativas()
    result = await tool.handler(tool.params(empresa="sunset"), _ctx())

    assert result.status is ToolStatus.OK
    assert result.summary["noticias_mostradas"] == 1
    assert result.summary["noticias"][0]["titulo"] == "Sunset abre temporada"


async def test_filters_by_categoria_natural_language() -> None:
    tool = noticias_corporativas()
    result = await tool.handler(tool.params(categoria="premios"), _ctx())

    assert result.status is ToolStatus.OK
    assert result.summary["noticias_mostradas"] == 1
    assert result.summary["noticias"][0]["titulo"] == "FBD Hotels gana premio"


async def test_unrecognised_categoria_is_ignored_not_rejected() -> None:
    """Un filtro de categoría que no se reconoce no debe vaciar el resultado: se ignora."""
    tool = noticias_corporativas()
    result = await tool.handler(tool.params(categoria="algo rarisimo"), _ctx())

    assert result.status is ToolStatus.OK
    assert result.summary["noticias_mostradas"] == 3


async def test_respects_limite() -> None:
    tool = noticias_corporativas()
    result = await tool.handler(tool.params(limite=1), _ctx())

    assert result.summary["noticias_mostradas"] == 1


async def test_presentation_is_a_news_list_with_rows() -> None:
    tool = noticias_corporativas()
    result = await tool.handler(tool.params(), _ctx())

    assert result.presentation is not None
    assert result.presentation["type"] == "news_list"
    assert len(result.presentation["news_rows"]) == 3
    assert result.presentation["news_rows"][0]["url"]


async def test_not_found_when_no_news_match_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    async def empty_fetch_all(client: object) -> tuple[list[NewsItem], list[str]]:
        del client
        return [], []

    monkeypatch.setattr(noticias_tools, "fetch_all", empty_fetch_all)
    tool = noticias_corporativas()
    result = await tool.handler(tool.params(), _ctx())

    assert result.status is ToolStatus.NOT_FOUND


async def test_source_unavailable_when_every_source_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    async def all_failed_fetch_all(client: object) -> tuple[list[NewsItem], list[str]]:
        del client
        return [], ["a", "b", "c", "d"]

    monkeypatch.setattr(noticias_tools, "fetch_all", all_failed_fetch_all)
    tool = noticias_corporativas()
    result = await tool.handler(tool.params(), _ctx())

    assert result.status is ToolStatus.SOURCE_UNAVAILABLE


async def test_partial_failure_still_returns_ok_with_aviso(monkeypatch: pytest.MonkeyPatch) -> None:
    async def partial_fetch_all(client: object) -> tuple[list[NewsItem], list[str]]:
        del client
        return list(FIXTURE_ITEMS), ["Google News: X"]

    monkeypatch.setattr(noticias_tools, "fetch_all", partial_fetch_all)
    tool = noticias_corporativas()
    result = await tool.handler(tool.params(), _ctx())

    assert result.status is ToolStatus.OK
    assert "Google News: X" in result.summary["aviso"]


def test_tool_requires_noticias_leer_permission() -> None:
    """Público en contenido, no en acceso: exige NOTICIAS_LEER, concedido a cualquier usuario con
    algún rol reconocido (ver mia.auth.context._UNIVERSAL_CON_ROL), nunca a quien no tiene ninguno."""
    tool = noticias_corporativas()
    assert tool.permission is Permission.NOTICIAS_LEER


# ------------------------------------------------------------------ regresión: fechas mixtas reales
_RSS_WITH_PUBDATE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><item>
  <title>FBD Hotels acquires the Grand Hotel Malahide - Irish Times</title>
  <link>https://news.google.com/rss/articles/AAAA</link>
  <pubDate>Mon, 20 Oct 2026 08:00:00 GMT</pubDate>
  <source url="https://irishtimes.com">Irish Times</source>
</item></channel></rss>"""

_FBD_HTML_WITH_DATE = """<!DOCTYPE html><html><body>
<h2>14th September 2026 - UK Share Trading Auction Results</h2>
<p>Please click <a href="/cmsFiles/statement.pdf">here</a> to read the statement.</p>
</body></html>"""


async def test_end_to_end_handles_the_real_mixed_timezone_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regresión de producción: pedir noticias del Grupo FBD mezclaba el feed de Google News
    (fecha con zona horaria) con la web oficial (fecha sin hora) y ``sort()`` lanzaba
    ``TypeError``, que ``ToolRegistry._run()`` convertía en el mensaje genérico «Error técnico al
    consultar la fuente de datos». Aquí se usa el ``fetch_all`` REAL (solo se sustituye el
    transporte HTTP), para no enmascarar este tipo de fallo como hacía el resto de la suite."""
    import httpx  # noqa: PLC0415

    from mia.modules.community.noticias.sources import fetch_all as real_fetch_all  # noqa: PLC0415

    def handler(request: httpx.Request) -> httpx.Response:
        if "farmerbusinessdevelopments" in str(request.url):
            return httpx.Response(200, text=_FBD_HTML_WITH_DATE)
        return httpx.Response(200, text=_RSS_WITH_PUBDATE)

    monkeypatch.setattr(noticias_tools, "fetch_all", real_fetch_all)
    monkeypatch.setattr(noticias_tools, "new_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    tool = noticias_corporativas()
    result = await tool.handler(tool.params(empresa="fbd_group"), _ctx())

    assert result.status is ToolStatus.OK
    assert result.summary["noticias_mostradas"] == 2

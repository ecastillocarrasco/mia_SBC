"""Parsing de las fuentes de noticias: RSS de Google News y la página de inversores de Farmer
Business Developments (sin feed propio). Sin red real: ``httpx.MockTransport`` sirve contenido
fijo, representativo de lo observado en las fuentes reales (verificado a mano en octubre de 2026).
"""

from __future__ import annotations

import httpx

from mia.modules.community.noticias.sources import (
    FBD_INVESTOR_NEWS_URL,
    GROUP_FBD,
    GROUP_SUNSET,
    fetch_all,
    fetch_fbd_investor_news,
    fetch_google_news,
)

_SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item>
  <title>FBD Hotels acquires the Grand Hotel Malahide - Irish Times</title>
  <link>https://news.google.com/rss/articles/AAAA</link>
  <pubDate>Mon, 20 Oct 2026 08:00:00 GMT</pubDate>
  <description>&lt;a href="https://irishtimes.com/x"&gt;FBD Hotels acquires the Grand Hotel Malahide&lt;/a&gt;&amp;nbsp;&lt;font color="#6f6f6f"&gt;Irish Times&lt;/font&gt;</description>
  <source url="https://irishtimes.com">Irish Times</source>
</item>
<item>
  <title>Noticia sin fuente explícita</title>
  <link>https://news.google.com/rss/articles/BBBB</link>
  <pubDate>Sun, 19 Oct 2026 10:00:00 GMT</pubDate>
  <description>Resumen breve de la noticia.</description>
</item>
</channel></rss>"""

_SAMPLE_FBD_HTML = """<!DOCTYPE html><html><body>
<h2>14th September 2026 - UK Share Trading Auction Results</h2>
<p>Please click <a href="/cmsFiles/statement.pdf">here</a> to read the statement.</p>
<h2>&nbsp;</h2>
<h2>15th of January 2025 - Announcement regarding acquisition of Grand Hotel Malahide by FBD Hotels &amp; Resorts</h2>
<p>Please click <a href="/cmsFiles/acquisition.pdf">here</a> to read the statement issued by the Company.</p>
<h2>17th June 2021 - Strategic Review announced at AGM</h2>
<p>The Chairman announced a strategic review at the AGM.</p>
<h2>20th August 2020 - Results of AGM</h2>
<p>The results of the AGM were announced to shareholders.</p>
</body></html>"""


_SAMPLE_RSS_BENALMADENA_NOISE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item>
  <title>Un fallecido por ahogamiento en la playa de La Verdad en Benalmádena - Andalucía Información</title>
  <link>https://news.google.com/rss/articles/NOISE1</link>
  <pubDate>Sat, 05 Sep 2026 07:00:00 GMT</pubDate>
  <source url="https://andaluciainformacion.es">Andalucía Información</source>
</item>
<item>
  <title>El temporal de viento deja numerosos daños en playas de la Costa del Sol - Cadena SER</title>
  <link>https://news.google.com/rss/articles/NOISE2</link>
  <pubDate>Sat, 13 Dec 2025 08:00:00 GMT</pubDate>
  <source url="https://cadenaser.com">Cadena SER</source>
</item>
<item>
  <title>El Equipo de Gobierno negocia con la dirección del Hotel Sunset Beach condiciones de uso de su área de aparcamiento - Ayuntamiento de Benalmádena</title>
  <link>https://news.google.com/rss/articles/RELEVANT1</link>
  <pubDate>Mon, 06 Jun 2016 07:00:00 GMT</pubDate>
  <source url="https://benalmadena.es">Ayuntamiento de Benalmádena</source>
</item>
</channel></rss>"""


def _mock_client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler)


async def test_fetch_google_news_filters_out_unrelated_local_news_by_relevance_terms() -> None:
    """Regresión de producción: la búsqueda ``"Sunset Beach Club" Benalmadena`` en Google News NO
    exige en la práctica que el título mencione el hotel — un ahogamiento o un temporal en una
    playa de Benalmádena cualquiera llegaban igual, y se presentaban como «noticias corporativas de
    Sunset Beach Club». Con ``relevance_terms`` solo sobrevive lo que de verdad lo nombra."""
    handler = httpx.MockTransport(lambda request: httpx.Response(200, text=_SAMPLE_RSS_BENALMADENA_NOISE))
    async with _mock_client(handler) as client:
        items = await fetch_google_news(
            client,
            "https://news.google.com/rss/search?q=x",
            grupo=GROUP_SUNSET,
            fuente_label="Google News: Sunset Beach Club",
            relevance_terms=("sunset beach",),
        )

    assert len(items) == 1
    assert "Sunset Beach" in items[0].titulo


async def test_fetch_google_news_parses_items_and_strips_source_suffix() -> None:
    handler = httpx.MockTransport(lambda request: httpx.Response(200, text=_SAMPLE_RSS))
    async with _mock_client(handler) as client:
        items = await fetch_google_news(
            client, "https://news.google.com/rss/search?q=x", grupo=GROUP_FBD, fuente_label="Google News: X"
        )

    assert len(items) == 2
    first = items[0]
    assert first.titulo == "FBD Hotels acquires the Grand Hotel Malahide"
    assert first.fuente == "Irish Times"
    assert first.grupo == GROUP_FBD
    assert first.publicado is not None and first.publicado.year == 2026
    assert first.resumen == ""  # la <description> de Google News no aporta nada sobre el título

    second = items[1]
    assert second.fuente == "Google News: X"  # sin <source>: usa la etiqueta de la propia fuente


async def test_fetch_fbd_investor_news_parses_dated_entries() -> None:
    handler = httpx.MockTransport(lambda request: httpx.Response(200, text=_SAMPLE_FBD_HTML))
    async with _mock_client(handler) as client:
        items = await fetch_fbd_investor_news(client)

    assert len(items) == 4  # el <h2>&nbsp;</h2> vacío se descarta
    assert items[0].titulo == "UK Share Trading Auction Results"
    assert items[0].publicado is not None
    assert items[0].publicado.day == 14 and items[0].publicado.month == 9 and items[0].publicado.year == 2026
    assert items[0].url.endswith("/cmsFiles/statement.pdf")

    assert "Grand Hotel Malahide" in items[1].titulo
    assert items[1].publicado is not None and items[1].publicado.year == 2025

    # Las dos últimas entradas no enlazan a ningún PDF: deben recibir URLs DISTINTAS (regresión:
    # si ambas caen a la URL genérica del listado, dedup.dedupe() las confundiría entre sí).
    assert items[2].url != items[3].url
    assert items[2].url.startswith(FBD_INVESTOR_NEWS_URL)
    assert items[3].url.startswith(FBD_INVESTOR_NEWS_URL)


async def test_fetch_all_skips_failing_sources_without_raising() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "farmerbusinessdevelopments" in str(request.url):
            return httpx.Response(200, text=_SAMPLE_FBD_HTML)
        return httpx.Response(503, text="unavailable")

    async with _mock_client(httpx.MockTransport(handler)) as client:
        items, failed = await fetch_all(client)

    assert len(failed) == 3  # los 3 feeds de Google News fallan con 503
    assert all("Google News" in label for label in failed)
    assert len(items) == 4  # la web oficial sí responde
    assert all(i.grupo == GROUP_FBD for i in items)


async def test_fetch_all_dates_are_all_timezone_aware_and_sortable() -> None:
    """Regresión: Google News trae ``pubDate`` con zona horaria (aware) y la web oficial de FBD
    solo fecha-sin-hora (naive) — mezclar ambas sin normalizar hacía que ``sort()`` en
    ``tools.noticias_corporativas`` lanzara ``TypeError: can't compare offset-naive and
    offset-aware datetimes`` en cuanto una respuesta real combinaba las dos fuentes (visto en
    producción al pedir noticias del Grupo FBD, que junta el feed de Google News con la web
    oficial)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "farmerbusinessdevelopments" in str(request.url):
            return httpx.Response(200, text=_SAMPLE_FBD_HTML)
        return httpx.Response(200, text=_SAMPLE_RSS)

    async with _mock_client(httpx.MockTransport(handler)) as client:
        items, failed = await fetch_all(client)

    assert not failed
    dated = [i for i in items if i.publicado is not None]
    assert dated  # ambas fuentes aportan fechas en esta mezcla
    assert all(i.publicado.tzinfo is not None for i in dated)
    sorted(items, key=lambda i: i.publicado or dated[0].publicado, reverse=True)  # no debe lanzar


async def test_fetch_all_reports_every_source_when_all_fail() -> None:
    handler = httpx.MockTransport(lambda request: httpx.Response(500, text="error"))
    async with _mock_client(handler) as client:
        items, failed = await fetch_all(client)

    assert items == []
    assert len(failed) == 4


async def test_sunset_feed_is_tagged_with_sunset_group() -> None:
    handler = httpx.MockTransport(lambda request: httpx.Response(200, text=_SAMPLE_RSS))
    async with _mock_client(handler) as client:
        items = await fetch_google_news(
            client,
            "https://news.google.com/rss/search?q=sunset",
            grupo=GROUP_SUNSET,
            fuente_label="Google News: Sunset",
        )
    assert all(i.grupo == GROUP_SUNSET for i in items)

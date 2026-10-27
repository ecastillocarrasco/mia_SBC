"""Fuentes externas de noticias corporativas y de grupo (Sunset Beach Club / Grupo FBD).

Cada fuente se consulta en el momento de la pregunta (sin persistencia): decisión explícita
porque el volumen es bajo y la frescura importa más que el tiempo de respuesta de este dominio
en concreto. ``fetch_all`` consulta todas las fuentes en paralelo y nunca deja que el fallo de
una tumbe a las demás.

``fbdhotels.com/news`` NO se consulta: está protegida por Cloudflare y responde 403 a cualquier
cliente HTTP de servidor (verificado). Sus noticias llegan igualmente a través del feed de Google
News "FBD Hotels" cuando terceros las publican o Google las indexa.
"""

from __future__ import annotations

import asyncio
import html
import re
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx
from defusedxml import ElementTree

from mia.modules.community.noticias.classify import classify_category
from mia.observability import get_logger
from mia.text import normalize_key

log = get_logger(__name__)

GROUP_SUNSET = "sunset"
GROUP_FBD = "fbd_group"

REQUEST_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
USER_AGENT = "Mozilla/5.0 (compatible; mIA-noticias/1.0; +https://sunsetbeachclub.com)"


@dataclass(frozen=True, slots=True)
class NewsItem:
    titulo: str
    url: str
    fuente: str
    grupo: str
    categoria: str
    publicado: datetime | None
    resumen: str = ""


def new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=True, headers={"User-Agent": USER_AGENT})


# ------------------------------------------------------------------ Google News RSS
_HTML_TAG = re.compile(r"<[^>]+>")
_TITLE_SOURCE_SUFFIX = re.compile(r"\s+-\s+[^-]{2,60}$")


def _strip_html(value: str | None) -> str:
    return re.sub(r"\s+", " ", html.unescape(_HTML_TAG.sub(" ", value or ""))).strip()


def _clean_google_title(title: str, source_name: str | None) -> str:
    """Google News añade " - <medio>" al final del título: se separa como ``fuente`` real."""
    if source_name and title.endswith(source_name):
        title = title[: -len(source_name)]
        title = title.rstrip(" -")
    return _TITLE_SOURCE_SUFFIX.sub("", title).strip() or title.strip()


def _as_utc(value: datetime | None) -> datetime | None:
    """Todas las fechas de ``NewsItem.publicado`` son UTC-aware, nunca naive: las fuentes se
    mezclan (RFC822 con zona de Google News, fecha-sin-hora de la web oficial) y comparar o
    restar una aware con una naive lanza ``TypeError`` — justo lo que rompía ``fetch_all`` al
    pedir noticias de FBD en producción (sort() mezclaba ambas)."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _parse_pubdate(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return _as_utc(parsedate_to_datetime(value))
    except (TypeError, ValueError):
        return None


def _is_relevant(title: str, relevance_terms: tuple[str, ...]) -> bool:
    """Google News no trata la consulta como un AND estricto de la frase entre comillas: el feed
    "Sunset Beach Club" Benalmadena devuelve, en la práctica, cualquier noticia local de
    Benalmádena (ahogamientos, temporales, sucesos...) aunque no mencionen el hotel. Filtrar en
    servidor por que el TÍTULO contenga de verdad el nombre es lo único que evita presentar esas
    noticias ajenas como si fueran "noticias corporativas de Sunset Beach Club"."""
    if not relevance_terms:
        return True
    text = normalize_key(title)
    return any(normalize_key(term) in text for term in relevance_terms)


async def fetch_google_news(
    client: httpx.AsyncClient, url: str, *, grupo: str, fuente_label: str, relevance_terms: tuple[str, ...] = ()
) -> list[NewsItem]:
    """Noticias de un feed de búsqueda de Google News (RSS estándar).

    ``defusedxml`` en vez de ``xml.etree`` directo: es contenido de un servidor externo, así que se
    trata como no confiable (sin resolución de entidades externas ni expansión recursiva)."""
    response = await client.get(url)
    response.raise_for_status()
    root = ElementTree.fromstring(response.content)
    items: list[NewsItem] = []
    for item in root.iter("item"):
        raw_title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not raw_title or not link:
            continue
        source_el = item.find("source")
        source_name = (source_el.text or "").strip() if source_el is not None else None
        title = _clean_google_title(raw_title, source_name)
        if not _is_relevant(title, relevance_terms):
            continue
        # La <description> de Google News es casi siempre el propio título envuelto en un enlace
        # más el nombre del medio (p. ej. "<a>Título</a>&nbsp;&nbsp;<font>Medio</font>"): no aporta
        # un resumen real, así que no se usa — se deja vacío en vez de repetir el título.
        items.append(
            NewsItem(
                titulo=title,
                url=link,
                fuente=source_name or fuente_label,
                grupo=grupo,
                categoria=classify_category(title),
                publicado=_parse_pubdate(item.findtext("pubDate")),
                resumen="",
            )
        )
    return items


GOOGLE_NEWS_FEEDS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (
        GROUP_SUNSET,
        "Google News: Sunset Beach Club",
        "https://news.google.com/rss/search?q=%22Sunset+Beach+Club%22+Benalmadena&hl=es&gl=ES&ceid=ES:es",
        ("sunset beach",),
    ),
    (
        GROUP_FBD,
        "Google News: FBD Hotels",
        "https://news.google.com/rss/search?q=%22FBD+Hotels%22&hl=en-IE&gl=IE&ceid=IE:en",
        ("fbd hotel", "fbd hotels"),
    ),
    (
        GROUP_FBD,
        "Google News: Farmer Business Developments",
        "https://news.google.com/rss/search?q=%22Farmer+Business+Developments%22&hl=en-IE&gl=IE&ceid=IE:en",
        ("farmer business development",),
    ),
)


# ------------------------------------------------------------------ Farmer Business Developments (web oficial)
FBD_INVESTOR_NEWS_URL = "https://www.farmerbusinessdevelopments.ie/latest-investor-news.html"
FBD_INVESTOR_NEWS_LABEL = "Farmer Business Developments (web oficial)"

_FBD_ENTRY = re.compile(r"<h2[^>]*>(.*?)</h2>\s*(?:<p[^>]*>(.*?)</p>)?", re.IGNORECASE | re.DOTALL)
_FBD_DATE_TITLE = re.compile(r"^\s*(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([A-Za-z]+)\s+(\d{4})\s*[-–—]\s*(.+?)\s*$")
_ORDINAL_OF = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s+of\s+", re.IGNORECASE)


def _parse_fbd_heading(raw: str) -> tuple[datetime | None, str]:
    heading = _strip_html(raw)
    heading = _ORDINAL_OF.sub(r"\1 ", heading)
    match = _FBD_DATE_TITLE.match(heading)
    if not match:
        return None, heading
    day, month, year, title = match.groups()
    try:
        published = datetime.strptime(f"{day} {month} {year}", "%d %B %Y")
    except ValueError:
        return None, heading
    return _as_utc(published), title.strip()


def _fbd_link(paragraph_html: str) -> str | None:
    """``None`` si la entrada no enlaza a ningún PDF (ocurre en varias noticias antiguas): nunca
    se devuelve la URL genérica del listado para dos noticias distintas, o ``dedup.dedupe()`` las
    trataría como la misma por tener "la misma URL"."""
    match = re.search(r'href="([^"]+)"', paragraph_html or "")
    if not match:
        return None
    href = match.group(1)
    return href if href.startswith("http") else f"https://www.farmerbusinessdevelopments.ie/{href.lstrip('/')}"


async def fetch_fbd_investor_news(client: httpx.AsyncClient) -> list[NewsItem]:
    """Página de noticias de inversores de Farmer Business Developments (sin feed RSS propio).

    Estructura estable comprobada (octubre 2026): cada noticia es un ``<h2>fecha - título</h2>``
    seguido de un ``<p>`` con el enlace al PDF o comunicado. Si el sitio rediseña esta página, esta
    función dejará de encontrar entradas y ``fetch_all`` lo tratará como fuente no disponible —
    nunca como un error que tumbe el resto de fuentes.
    """
    response = await client.get(FBD_INVESTOR_NEWS_URL)
    response.raise_for_status()
    body = response.text
    items: list[NewsItem] = []
    for heading_html, paragraph_html in _FBD_ENTRY.findall(body):
        published, title = _parse_fbd_heading(heading_html)
        if not title:
            continue
        resumen = _strip_html(paragraph_html)
        link = _fbd_link(paragraph_html)
        if link is None:
            # Sin PDF enlazado: un ancla propia (no la URL genérica del listado) para que dos
            # noticias sin enlace nunca se confundan entre sí en dedup.dedupe().
            slug = normalize_key(title).replace(" ", "-") or "noticia"
            link = f"{FBD_INVESTOR_NEWS_URL}#{slug}-{published.date() if published else ''}"
        items.append(
            NewsItem(
                titulo=title,
                url=link,
                fuente=FBD_INVESTOR_NEWS_LABEL,
                grupo=GROUP_FBD,
                categoria=classify_category(title, resumen),
                publicado=published,
                resumen=resumen,
            )
        )
    return items


# ------------------------------------------------------------------ orquestación de fuentes
async def fetch_all(client: httpx.AsyncClient) -> tuple[list[NewsItem], list[str]]:
    """Todas las fuentes en paralelo. Devuelve los elementos obtenidos y la etiqueta de las fuentes
    que han fallado (nunca lanza: una fuente caída no debe impedir ver las demás)."""

    async def _safe(label: str, coro: Awaitable[list[NewsItem]]) -> tuple[str, list[NewsItem] | None]:
        try:
            return label, await coro
        except (httpx.HTTPError, ElementTree.ParseError) as exc:
            log.warning("noticias.fuente_no_disponible", fuente=label, error=str(exc)[:200])
            return label, None

    # La fuente oficial va primero en la lista (aunque las tareas corran todas en paralelo, el
    # ORDEN DE LLEGADA a `items` sigue el orden de `tasks`, no el de finalización real —
    # asyncio.gather conserva el orden de los awaitables de entrada): así, cuando Google News
    # recoge la misma nota de prensa que ya trae la web oficial, dedup.dedupe() conserva la
    # versión oficial (más limpia) en vez de la recogida por el agregador.
    tasks = [_safe(FBD_INVESTOR_NEWS_LABEL, fetch_fbd_investor_news(client))]
    tasks += [
        _safe(
            fuente_label,
            fetch_google_news(client, url, grupo=grupo, fuente_label=fuente_label, relevance_terms=relevance_terms),
        )
        for grupo, fuente_label, url, relevance_terms in GOOGLE_NEWS_FEEDS
    ]

    results = await asyncio.gather(*tasks)
    items: list[NewsItem] = []
    failed: list[str] = []
    for label, result in results:
        if result is None:
            failed.append(label)
        else:
            items.extend(result)
    return items, failed

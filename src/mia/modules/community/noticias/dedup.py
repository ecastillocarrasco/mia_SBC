"""Eliminación de duplicados entre fuentes de noticias.

La misma noticia puede llegar dos veces: recogida por dos feeds de Google News distintos (p. ej.
una nota de prensa de FBD Hotels que también menciona a Farmer Business Developments), o publicada
en la web oficial Y recogida además por Google News. No hay un identificador común fiable (los
enlaces de Google News son redirecciones opacas, no la URL del artículo original), así que la
comparación es por URL normalizada y, si no coincide, por similitud de título.
"""

from __future__ import annotations

import difflib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from mia.modules.community.noticias.sources import NewsItem
from mia.text import normalize_key

TITLE_SIMILARITY_THRESHOLD = 0.88


def normalize_url(url: str) -> str:
    """Mismo artículo, distinta URL superficial: sin parámetros de tracking (utm_*), sin "www.",
    sin barra final. El fragmento (#...) SÍ se conserva: ``sources.fetch_fbd_investor_news`` lo usa
    para dar una identidad propia a noticias sin PDF enlazado, que de otro modo comparten la URL
    genérica del listado — descartarlo aquí las confundiría entre sí."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith("utm_")]
    netloc = parts.netloc.lower()
    netloc = netloc.removeprefix("www.")
    return urlunsplit((parts.scheme.lower(), netloc, parts.path.rstrip("/"), urlencode(sorted(query)), parts.fragment))


MAX_DUPLICATE_DATE_GAP_DAYS = 3
"""Fuentes como las notas de inversores reutilizan el MISMO título plantilla cada año
("Publication of Chairman's Statement for 2024", "...for 2025"…): un título casi idéntico NO es
un duplicado si las fechas están muy alejadas — son ediciones distintas de una noticia recurrente,
nunca el mismo hecho contado dos veces. Solo se exige esta cercanía cuando AMBAS noticias traen
fecha; sin fecha, se cae de vuelta a comparar solo el título (más fuentes no quiere decir fechas
siempre fiables)."""


def _is_duplicate(a: NewsItem, b: NewsItem) -> bool:
    # Nunca fundir noticias de empresas/grupos distintos entre sí: haría desaparecer un resultado
    # legítimo del filtro por empresa (p. ej. si "FBD Hotels" y "Sunset Beach Club" coinciden en
    # un mismo artículo, cada bando debe poder seguir viéndolo bajo su propia etiqueta).
    if a.grupo != b.grupo:
        return False
    if normalize_url(a.url) == normalize_url(b.url):
        return True
    title_a, title_b = normalize_key(a.titulo), normalize_key(b.titulo)
    if not title_a or not title_b:
        return False
    ratio = difflib.SequenceMatcher(None, title_a, title_b).ratio()
    if title_a != title_b and ratio < TITLE_SIMILARITY_THRESHOLD:
        return False
    if a.publicado and b.publicado:
        return abs((a.publicado - b.publicado).days) <= MAX_DUPLICATE_DATE_GAP_DAYS
    return True


def dedupe(items: list[NewsItem]) -> list[NewsItem]:
    """Conserva la primera aparición de cada noticia (ver el orden deliberado en
    ``sources.fetch_all``: la fuente oficial llega antes que los agregadores)."""
    kept: list[NewsItem] = []
    for item in items:
        if not any(_is_duplicate(item, other) for other in kept):
            kept.append(item)
    return kept

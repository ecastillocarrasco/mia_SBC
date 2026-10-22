"""Eliminación de duplicados entre fuentes de noticias (Google News + web oficial)."""

from __future__ import annotations

from datetime import datetime

from mia.modules.community.noticias.dedup import dedupe, normalize_url
from mia.modules.community.noticias.sources import GROUP_FBD, GROUP_SUNSET, NewsItem


def _item(titulo: str, url: str, fuente: str = "Fuente") -> NewsItem:
    return NewsItem(
        titulo=titulo, url=url, fuente=fuente, grupo=GROUP_FBD,
        categoria="corporativo_general", publicado=datetime(2026, 1, 1),
    )


def test_normalize_url_strips_tracking_params_and_www() -> None:
    a = normalize_url("https://WWW.Example.com/news/article/?utm_source=chatgpt.com&id=1")
    b = normalize_url("https://example.com/news/article?id=1")
    assert a == b


def test_normalize_url_strips_trailing_slash() -> None:
    assert normalize_url("https://example.com/news/") == normalize_url("https://example.com/news")


def test_dedupe_keeps_first_seen_same_url() -> None:
    items = [
        _item("Artículo oficial", "https://farmerbusinessdevelopments.ie/cmsFiles/a.pdf", "Oficial"),
        _item("Artículo oficial (recogido por Google)", "https://farmerbusinessdevelopments.ie/cmsFiles/a.pdf", "Google News"),
    ]
    out = dedupe(items)
    assert len(out) == 1
    assert out[0].fuente == "Oficial"


def test_dedupe_merges_near_identical_titles_with_different_urls() -> None:
    """Enlaces de Google News: la misma noticia llega con URLs de redirección distintas."""
    items = [
        _item(
            "FBD Hotels acquires the Grand Hotel Malahide",
            "https://news.google.com/rss/articles/AAAA",
            "Irish Times",
        ),
        _item(
            "FBD Hotels acquires the Grand Hotel Malahide ",
            "https://news.google.com/rss/articles/BBBB",
            "RTE",
        ),
    ]
    out = dedupe(items)
    assert len(out) == 1


def test_dedupe_does_not_merge_different_items_sharing_an_anchored_fallback_url() -> None:
    """Dos noticias sin PDF enlazado (caso real en farmerbusinessdevelopments.ie) no deben
    confundirse entre sí solo porque ambas apuntan a la misma página con un ancla distinta —
    ``sources.fetch_fbd_investor_news`` las distingue precisamente por esto."""
    base = "https://farmerbusinessdevelopments.ie/latest-investor-news.html"
    a = _item("Results of AGM", f"{base}#results-of-agm-2020-08-20")
    b = _item("Strategic Review announced at AGM", f"{base}#strategic-review-announced-at-agm-2021-06-17")
    out = dedupe([a, b])
    assert len(out) == 2


def test_dedupe_keeps_genuinely_different_news() -> None:
    items = [
        _item("FBD Hotels acquires the Grand Hotel Malahide", "https://a.test/1", "A"),
        _item("Farmer Business Developments publishes 2025 annual report", "https://b.test/2", "B"),
    ]
    out = dedupe(items)
    assert len(out) == 2


def test_dedupe_never_merges_across_different_groups() -> None:
    """Un mismo artículo (misma URL) no debe desaparecer del filtro por empresa de ninguno de los
    dos bandos: si por lo que sea se recoge etiquetado tanto de Sunset como de FBD, cada uno debe
    conservar su propia copia — fundirlas haría que, por ejemplo, pedir «noticias del grupo FBD»
    se quedara sin ese resultado solo porque dedupe() vio antes la versión de Sunset."""
    sunset = NewsItem(
        titulo="Mismo artículo", url="https://a.test/x", fuente="A",
        grupo=GROUP_SUNSET, categoria="corporativo_general", publicado=datetime(2026, 1, 1),
    )
    fbd = NewsItem(
        titulo="Mismo artículo", url="https://a.test/x", fuente="A",
        grupo=GROUP_FBD, categoria="corporativo_general", publicado=datetime(2026, 1, 1),
    )
    out = dedupe([sunset, fbd])
    assert len(out) == 2
    assert {i.grupo for i in out} == {GROUP_SUNSET, GROUP_FBD}


def test_dedupe_does_not_merge_recurring_yearly_titles_from_different_years() -> None:
    """Farmer Business Developments repite el mismo título plantilla cada año ("Publication of
    Chairman's Statement for 2024" / "...for 2025"): son noticias DISTINTAS, no el mismo hecho
    recogido dos veces, aunque el título normalizado sea casi idéntico."""
    old = NewsItem(
        titulo="Publication of Chairman's Statement for 2024", url="https://a.test/2024-statement",
        fuente="Oficial", grupo=GROUP_FBD, categoria="inversion_financiera",
        publicado=datetime(2025, 5, 20),
    )
    new = NewsItem(
        titulo="Publication of Chairman's Statement for 2025", url="https://a.test/2025-statement",
        fuente="Oficial", grupo=GROUP_FBD, categoria="inversion_financiera",
        publicado=datetime(2026, 5, 19),
    )
    out = dedupe([old, new])
    assert len(out) == 2

"""Cuerpo de un correo HTML → texto limpio y legible (párrafos, listas y enlaces), sin CSS ni marcas.

La limpieza anterior solo quitaba las etiquetas: el contenido de ``<style>`` (cientos de líneas de CSS) acababa
como texto y todos los saltos de línea se perdían.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

_SKIP = {"style", "script", "head", "title", "noscript", "template", "svg"}
_BLOCK = {"p", "div", "br", "tr", "table", "section", "article", "header", "footer", "blockquote", "ul", "ol", "hr"}
_HEADING = {"h1", "h2", "h3", "h4", "h5", "h6"}
_INVISIBLE = re.compile("[\u200b-\u200f\u034f\u00ad\ufeff\u2060\u2007\u2800]")
_HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden|max-height\s*:\s*0|font-size\s*:\s*0", re.I)
_URL = re.compile(r"^https?://", re.I)


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0
        self._hidden: list[str] = []  # etiquetas abiertas que están ocultas (p. ej. el texto previo del correo)
        self._links: list[str | None] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag in _SKIP:
            self._skip += 1
            return
        if self._hidden or "hidden" in a or _HIDDEN_STYLE.search(a.get("style") or ""):
            if tag not in {"br", "img", "hr", "meta", "link", "input"}:
                self._hidden.append(tag)
            return
        if tag in _HEADING:
            self.parts.append("\n\n")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in {"td", "th"}:
            self.parts.append(" ")
        elif tag in _BLOCK:
            self.parts.append("\n")
        if tag == "a":
            self._links.append(a.get("href"))

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            self._skip = max(0, self._skip - 1)
            return
        if self._hidden:
            if tag == self._hidden[-1]:
                self._hidden.pop()
            return
        if tag == "a" and self._links:
            href = self._links.pop()
            if href and _URL.match(href):
                self.parts.append(f" ({href})")
        elif tag in _HEADING or tag in {"p", "div", "tr", "table", "ul", "ol", "blockquote"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip and not self._hidden:
            self.parts.append(data)


def html_to_text(content: str, limit: int = 12000) -> str:
    parser = _Extractor()
    try:
        parser.feed(re.sub(r"<!--.*?-->", "", content, flags=re.S))
        parser.close()
    except Exception:  # HTML muy roto: mejor algo de texto que nada
        return _tidy(re.sub(r"<[^>]+>", " ", content))[:limit]
    return _tidy("".join(parser.parts))[:limit]


def _tidy(text: str) -> str:
    text = _INVISIBLE.sub("", text).replace("\r", "").replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


def plain_text(content: str, content_type: str = "text", limit: int = 12000) -> str:
    """Texto legible de un cuerpo de correo, sea HTML o texto plano."""
    return html_to_text(content, limit) if content_type.lower() == "html" else _tidy(content)[:limit]

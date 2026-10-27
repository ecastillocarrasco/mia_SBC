"""Normalización de texto para comparar nombres, departamentos, etc."""

from __future__ import annotations

import re
import unicodedata
from html.parser import HTMLParser

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_key(value: object) -> str:
    """Minúsculas, sin tildes ni signos: "Ángela  Pérez-Ruiz" → "angela perez ruiz"."""
    text = unicodedata.normalize("NFKD", str(value or "").lower().strip())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return _NON_ALNUM.sub(" ", text).strip()


_LABEL_WORDS = {
    "nominas": "nóminas",
    "nomina": "nómina",
    "leidas": "leídas",
    "leidos": "leídos",
    "leida": "leída",
    "dias": "días",
    "anio": "año",
    "anios": "años",
    "telefono": "teléfono",
    "codigo": "código",
    "situacion": "situación",
    "organizacion": "organización",
    "documentacion": "documentación",
    "proximos": "próximos",
    "proximas": "próximas",
    "proximo": "próximo",
    "proxima": "próxima",
    "ultima": "última",
    "ultimo": "último",
    "cumpleanos": "cumpleaños",
    "medico": "médico",
    "prevencion": "prevención",
    "informacion": "información",
    "duracion": "duración",
    "maximo": "máximo",
    "minimo": "mínimo",
    "numero": "número",
    "periodo": "período",
    "periodos": "períodos",
    "tecnico": "técnico",
    "calculada": "calculada",
    "reincorporacion": "reincorporación",
    "direccion": "dirección",
}
_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])")


def humanize_label(key: object) -> str:
    """«nominas_no_leidas» → «Nóminas no leídas»: etiqueta legible y con tildes para pantalla e informes."""
    words = _CAMEL.sub(" ", str(key)).replace("_", " ").split()
    if not words:
        return ""
    fixed = [_LABEL_WORDS.get(w.lower(), w.lower()) if w.upper() != w or len(w) > 3 else w for w in words]
    text = " ".join(fixed)
    return text[:1].upper() + text[1:]


def format_number(value: float) -> str:
    """0.0 → «0», 24.0 → «24», 2.5 → «2,5», 1234.5 → «1.234,5», 8.8 → «8,8» (formato español)."""
    if float(value).is_integer():
        return f"{int(value):,}".replace(",", ".") if abs(value) >= 10000 else str(int(value))
    text = f"{value:,.2f}".rstrip("0").rstrip(".")
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


# ------------------------------------------------------------------ HTML a texto plano
# Usado por el cuerpo de correo (mia.modules.correo) y por el cuerpo rico de listas de
# SharePoint (p. ej. Community/Newsletter): ningun dominio es dueno de "convertir HTML a texto
# legible", asi que vive aqui, no en uno de los dos.
_HTML_SKIP = {"style", "script", "head", "title", "noscript", "template", "svg"}
_HTML_BLOCK = {
    "p",
    "div",
    "br",
    "tr",
    "table",
    "section",
    "article",
    "header",
    "footer",
    "blockquote",
    "ul",
    "ol",
    "hr",
}
_HTML_HEADING = {"h1", "h2", "h3", "h4", "h5", "h6"}
_INVISIBLE = re.compile("[\u200b\u200c\u200d\u200e\u200f\u034f\u00ad\ufeff\u2060\u2007\u2800]")
_HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden|max-height\s*:\s*0|font-size\s*:\s*0", re.I)
_HTML_URL = re.compile(r"^https?://", re.I)


class _HtmlTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0
        self._hidden: list[str] = []  # etiquetas abiertas que estan ocultas (p. ej. el texto previo del correo)
        self._links: list[str | None] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag in _HTML_SKIP:
            self._skip += 1
            return
        if self._hidden or "hidden" in a or _HIDDEN_STYLE.search(a.get("style") or ""):
            if tag not in {"br", "img", "hr", "meta", "link", "input"}:
                self._hidden.append(tag)
            return
        if tag in _HTML_HEADING:
            self.parts.append("\n\n")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in {"td", "th"}:
            self.parts.append(" ")
        elif tag in _HTML_BLOCK:
            self.parts.append("\n")
        if tag == "a":
            self._links.append(a.get("href"))

    def handle_endtag(self, tag: str) -> None:
        if tag in _HTML_SKIP:
            self._skip = max(0, self._skip - 1)
            return
        if self._hidden:
            if tag == self._hidden[-1]:
                self._hidden.pop()
            return
        if tag == "a" and self._links:
            href = self._links.pop()
            if href and _HTML_URL.match(href):
                self.parts.append(f" ({href})")
        elif tag in _HTML_HEADING or tag in {"p", "div", "tr", "table", "ul", "ol", "blockquote"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip and not self._hidden:
            self.parts.append(data)


def html_to_text(content: str, limit: int = 12000) -> str:
    parser = _HtmlTextExtractor()
    try:
        parser.feed(re.sub(r"<!--.*?-->", "", content, flags=re.S))
        parser.close()
    except Exception:  # HTML muy roto: mejor algo de texto que nada
        return _tidy_html_text(re.sub(r"<[^>]+>", " ", content))[:limit]
    return _tidy_html_text("".join(parser.parts))[:limit]


def _tidy_html_text(text: str) -> str:
    text = _INVISIBLE.sub("", text).replace("\r", "").replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


def plain_text(content: str, content_type: str = "text", limit: int = 12000) -> str:
    """Texto legible de un cuerpo HTML o texto plano (correo, campos de SharePoint con texto enriquecido...)."""
    return html_to_text(content, limit) if content_type.lower() == "html" else _tidy_html_text(content)[:limit]

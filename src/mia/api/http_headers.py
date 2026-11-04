"""Cabeceras HTTP compartidas por las rutas de descarga (correo, informes, documentos)."""

from __future__ import annotations

from urllib.parse import quote


def content_disposition(disposition: str, filename: str) -> str:
    """Construye un valor de `Content-Disposition` seguro para nombres fuera de Latin-1.

    Starlette codifica los valores de cabecera como Latin-1: un nombre de archivo con CJK,
    árabe, cirílico o emoji (plausible en un adjunto de correo externo, fuera de nuestro
    control) provoca un `UnicodeEncodeError` al construir la respuesta, es decir, un 500 al
    intentar abrir ese archivo en vez de solo un nombre mal mostrado. `filename*=UTF-8''...`
    (RFC 6266 / 5987) lleva el nombre real; `filename="..."` es un equivalente ASCII para los
    clientes que no entienden esa extensión.
    """
    safe = filename.replace('"', "").replace("\r", "").replace("\n", "")
    ascii_fallback = safe.encode("ascii", "replace").decode("ascii").replace("?", "_") or "archivo"
    return f"{disposition}; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(safe)}"

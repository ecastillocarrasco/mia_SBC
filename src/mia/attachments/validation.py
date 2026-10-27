"""Validación de seguridad para archivos adjuntos."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

# Tipos MIME permitidos por grupo
ALLOWED_MIME = frozenset(
    {
        # Imágenes
        "image/png",
        "image/jpeg",
        "image/webp",
        # Documentos
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # docx
        "text/plain",
        "text/markdown",
        "text/x-markdown",
        # Datos
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # xlsx
        "application/vnd.ms-excel",  # xls
        "text/csv",
        "application/csv",
        "text/x-csv",
    }
)

ALLOWED_EXTENSIONS = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".pdf",
        ".docx",
        ".txt",
        ".md",
        ".xlsx",
        ".xls",
        ".csv",
    }
)

# Magic bytes → MIME real
_MAGIC: list[tuple[bytes, str]] = [
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"RIFF", "image/webp"),  # heurística; la comprobación completa está abajo
    (b"%PDF", "application/pdf"),
    (b"PK\x03\x04", "_zip"),  # zip; docx/xlsx se confirman por extensión
]

# Extensiones absolutamente peligrosas
_DANGEROUS_EXTENSIONS = frozenset(
    {
        ".exe",
        ".bat",
        ".cmd",
        ".sh",
        ".ps1",
        ".vbs",
        ".js",
        ".jar",
        ".com",
        ".scr",
        ".msi",
        ".dll",
        ".py",
        ".rb",
        ".php",
    }
)

_SAFE_FILENAME = re.compile(r"[^\w\s\-.()\[\]#@!+]", re.UNICODE)
_MAX_FILENAME_LEN = 200


@dataclass(frozen=True, slots=True)
class ValidationResult:
    ok: bool
    detected_mime: str
    error: str = ""


def _detect_mime(content: bytes) -> str:
    """Detecta el tipo MIME real por magic bytes."""
    for magic, mime in _MAGIC:
        if content.startswith(magic):
            if mime == "_zip":
                return mime  # se refinará por extensión
            if mime == "image/webp" and b"WEBP" not in content[4:16]:
                continue
            return mime
    if content.startswith(b"\xef\xbb\xbf") or all(c < 128 or c in (0xC0, 0xC2, 0xC3) for c in content[:500]):
        return "text/plain"
    return "application/octet-stream"


def _zip_to_office(detected: str, extension: str) -> str:
    if detected == "_zip":
        if extension in (".docx",):
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if extension in (".xlsx",):
            return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return "application/zip"
    return detected


def sanitize_filename(name: str) -> str:
    """Devuelve un nombre seguro: sin rutas, sin caracteres especiales, límite de longitud."""
    # Extraer solo el nombre base (sin paths traversal)
    name = PurePosixPath(name.replace("\\", "/")).name
    # Quitar caracteres no seguros
    name = _SAFE_FILENAME.sub("_", name)
    name = name.strip(". ")
    if not name:
        name = "archivo"
    return name[:_MAX_FILENAME_LEN]


def validate(
    content: bytes,
    filename: str,
    declared_mime: str,
    max_bytes: int,
) -> ValidationResult:
    """Valida un archivo adjunto. Devuelve ValidationResult con ok=False si no pasa."""
    if not content:
        return ValidationResult(ok=False, detected_mime="", error="El archivo está vacío.")

    if len(content) > max_bytes:
        mb = max_bytes // (1024 * 1024)
        return ValidationResult(ok=False, detected_mime="", error=f"El archivo supera el tamaño máximo de {mb} MB.")

    safe_name = sanitize_filename(filename)
    ext = PurePosixPath(safe_name).suffix.lower()

    if ext in _DANGEROUS_EXTENSIONS:
        return ValidationResult(ok=False, detected_mime="", error="Este tipo de archivo no está permitido.")

    if ext and ext not in ALLOWED_EXTENSIONS:
        return ValidationResult(ok=False, detected_mime="", error=f"Extensión «{ext}» no soportada todavía.")

    detected = _detect_mime(content)
    detected = _zip_to_office(detected, ext)

    if detected not in ALLOWED_MIME and detected != "application/octet-stream":
        return ValidationResult(ok=False, detected_mime=detected, error="Tipo de archivo no permitido.")

    if detected == "application/octet-stream" and (not ext or ext not in ALLOWED_EXTENSIONS):
        return ValidationResult(ok=False, detected_mime=detected, error="No se puede determinar el tipo de archivo.")

    # CSV/TXT/MD sin magic bytes son aceptados si el MIME declarado o la extensión coincide
    if detected == "application/octet-stream":
        detected = declared_mime if declared_mime in ALLOWED_MIME else "text/plain"

    # text/plain es ambiguo: respetar el declared_mime cuando es más específico (csv, markdown)
    if detected == "text/plain" and declared_mime in ALLOWED_MIME and declared_mime != "text/plain":
        detected = declared_mime
    elif detected == "text/plain" and ext in (".csv",):
        detected = "text/csv"
    elif detected == "text/plain" and ext in (".md",):
        detected = "text/markdown"

    return ValidationResult(ok=True, detected_mime=detected)


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()

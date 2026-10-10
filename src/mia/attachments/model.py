"""Modelo de datos para adjuntos conversacionales de mIA."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class AttachmentStatus(StrEnum):
    UPLOADING = "uploading"
    VALIDATING = "validating"
    PROCESSING = "processing"
    READY = "ready"
    ERROR = "error"
    EXPIRED = "expired"


class AttachmentContentType(StrEnum):
    IMAGE = "image"
    DOCUMENT = "document"
    DATASET = "dataset"


class AttachmentScope(StrEnum):
    CONVERSATION = "conversation"


class DataClassification(StrEnum):
    GENERAL = "general"
    INTERNAL = "internal"
    PERSONAL = "personal"
    HR_SENSITIVE = "hr_sensitive"
    PAYROLL_SENSITIVE = "payroll_sensitive"


@dataclass(frozen=True, slots=True)
class TableBlock:
    headers: list[str]
    rows: list[list[Any]]
    source_ref: str = ""
    """Origen: 'sheet=Octubre', 'page=3', 'heading=Tabla 1'…"""


@dataclass(frozen=True, slots=True)
class TextBlock:
    text: str
    source_ref: str = ""
    """Origen: 'page=7', 'heading=Conclusiones', 'paragraph=14'…"""


@dataclass(frozen=True, slots=True)
class DatasetSheet:
    name: str
    headers: list[str]
    rows: list[list[Any]]
    inferred_types: dict[str, str] = field(default_factory=dict)
    row_count: int = 0


@dataclass
class AttachmentContent:
    """Representación normalizada del contenido extraído, independiente del formato original."""

    content_type: AttachmentContentType
    text_blocks: list[TextBlock] = field(default_factory=list)
    tables: list[TableBlock] = field(default_factory=list)
    sheets: list[DatasetSheet] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    """Metadatos del documento: page_count, author, title, sheet_count…"""
    vision_description: str = ""
    """Resultado de Vision para imágenes o páginas escaneadas."""
    parse_error: str = ""
    """Mensaje si el parser encontró problemas parciales."""

    @property
    def full_text(self) -> str:
        return "\n\n".join(b.text for b in self.text_blocks if b.text)

    @property
    def page_count(self) -> int:
        return int(self.metadata.get("page_count", 0))

    @property
    def sheet_count(self) -> int:
        return len(self.sheets)

    @property
    def total_rows(self) -> int:
        return sum(s.row_count for s in self.sheets)


@dataclass
class AttachmentRecord:
    """Registro completo de un adjunto temporal."""

    attachment_id: str
    tenant_id: str
    user_id: str
    session_id: str | None

    original_filename: str
    mime_type: str
    detected_mime_type: str
    extension: str
    size_bytes: int

    created_at: datetime
    expires_at: datetime

    status: AttachmentStatus
    content_type: AttachmentContentType | None = None

    storage_location: str = ""
    sha256: str = ""
    classification: DataClassification = DataClassification.GENERAL
    scope: AttachmentScope = AttachmentScope.CONVERSATION

    content: AttachmentContent | None = None
    error_message: str = ""

    processing_duration_ms: int = 0
    parser_used: str = ""
    vision_used: bool = False
    chunks_count: int = 0
    tables_count: int = 0


@dataclass(frozen=True, slots=True)
class AttachmentRef:
    """Referencia ligera almacenada en session state (sin contenido completo)."""

    attachment_id: str
    filename: str
    content_type: AttachmentContentType | None
    size_bytes: int
    status: AttachmentStatus

    def to_dict(self) -> dict[str, Any]:
        return {
            "attachment_id": self.attachment_id,
            "filename": self.filename,
            "content_type": self.content_type.value if self.content_type else None,
            "size_bytes": self.size_bytes,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AttachmentRef:
        ct = d.get("content_type")
        return cls(
            attachment_id=d["attachment_id"],
            filename=d.get("filename", ""),
            content_type=AttachmentContentType(ct) if ct else None,
            size_bytes=int(d.get("size_bytes", 0)),
            status=AttachmentStatus(d.get("status", AttachmentStatus.READY)),
        )


SESSION_KEY_ACTIVE = "adjuntos_activos"


def get_active_refs(state: dict[str, Any]) -> list[AttachmentRef]:
    raw = state.get(SESSION_KEY_ACTIVE) or []
    if not isinstance(raw, list):
        return []
    result = []
    for item in raw:
        if isinstance(item, dict):
            try:
                result.append(AttachmentRef.from_dict(item))
            except (KeyError, ValueError):
                pass
    return result


def set_active_refs(state: dict[str, Any], refs: list[AttachmentRef]) -> None:
    state[SESSION_KEY_ACTIVE] = [r.to_dict() for r in refs]


def merge_refs(existing: list[AttachmentRef], new: list[AttachmentRef]) -> list[AttachmentRef]:
    """Agrega nuevas refs sin duplicar por attachment_id. Límite de 10."""
    ids = {r.attachment_id for r in existing}
    merged = list(existing)
    for ref in new:
        if ref.attachment_id not in ids:
            merged.append(ref)
            ids.add(ref.attachment_id)
    return merged[-10:]

"""Módulo de adjuntos conversacionales de mIA.

Los adjuntos son fuentes de contexto temporales que el LLM puede consultar
durante una conversación. No se indexan automáticamente en el RAG corporativo.
"""

from mia.attachments.model import (
    AttachmentContent,
    AttachmentContentType,
    AttachmentRecord,
    AttachmentRef,
    AttachmentScope,
    AttachmentStatus,
    get_active_refs,
    merge_refs,
    set_active_refs,
)
from mia.attachments.service import AttachmentService

__all__ = [
    "AttachmentContent",
    "AttachmentContentType",
    "AttachmentRecord",
    "AttachmentRef",
    "AttachmentScope",
    "AttachmentService",
    "AttachmentStatus",
    "get_active_refs",
    "merge_refs",
    "set_active_refs",
]

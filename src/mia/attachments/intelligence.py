"""Attachment Intelligence: clasificación, selección de parser y normalización.

Esta capa decide cómo procesar cada adjunto. No conoce ni depende del LLM
directamente; recibe el LLMProvider solo para llamar a Vision cuando sea necesario.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from mia.attachments.model import (
    AttachmentContent,
    AttachmentContentType,
    AttachmentRecord,
    AttachmentStatus,
    DataClassification,
)
from mia.observability import get_logger

if TYPE_CHECKING:
    from mia.llm import LLMProvider

log = get_logger(__name__)

# Mapa MIME → content_type
_MIME_TO_CONTENT_TYPE: dict[str, AttachmentContentType] = {
    "image/png": AttachmentContentType.IMAGE,
    "image/jpeg": AttachmentContentType.IMAGE,
    "image/webp": AttachmentContentType.IMAGE,
    "application/pdf": AttachmentContentType.DOCUMENT,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": AttachmentContentType.DOCUMENT,
    "text/plain": AttachmentContentType.DOCUMENT,
    "text/markdown": AttachmentContentType.DOCUMENT,
    "text/x-markdown": AttachmentContentType.DOCUMENT,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": AttachmentContentType.DATASET,
    "application/vnd.ms-excel": AttachmentContentType.DATASET,
    "text/csv": AttachmentContentType.DATASET,
    "application/csv": AttachmentContentType.DATASET,
    "text/x-csv": AttachmentContentType.DATASET,
}

# Clasificación de datos según el nombre del archivo (heurística ligera)
_HR_PATTERNS = ("cv", "curriculum", "nomina", "nómina", "contrato", "alta", "baja", "vacaciones")
_PAYROLL_PATTERNS = ("nomina", "nómina", "salario", "sueldo", "payroll", "retribucion")


def classify_content_type(mime: str) -> AttachmentContentType | None:
    return _MIME_TO_CONTENT_TYPE.get(mime)


def classify_data(filename: str, content_type: AttachmentContentType | None) -> DataClassification:
    name = filename.lower()
    if any(p in name for p in _PAYROLL_PATTERNS):
        return DataClassification.PAYROLL_SENSITIVE
    if any(p in name for p in _HR_PATTERNS):
        return DataClassification.HR_SENSITIVE
    if content_type == AttachmentContentType.DOCUMENT:
        return DataClassification.INTERNAL
    return DataClassification.GENERAL


_VISION_INSTRUCTION = (
    "Describe en español el contenido completo de esta imagen con detalle. "
    "Si contiene texto, transcríbelo. Si es una captura de pantalla, "
    "identifica la aplicación, los campos visibles, valores y cualquier "
    "mensaje de error. Si es un documento, describe su estructura y contenido. "
    "Si es una tabla o gráfico, describe los datos que muestra."
)

_SCANNED_PDF_INSTRUCTION = (
    "Transcribe y describe el contenido de esta página de documento. "
    "Incluye todos los textos, tablas y datos visibles."
)


async def process_attachment(
    record: AttachmentRecord,
    raw_content: bytes,
    llm: "LLMProvider | None",
    vision_enabled: bool = True,
) -> AttachmentRecord:
    """Procesa el archivo y rellena record.content. Modifica record in-place."""
    started = time.perf_counter()
    record.status = AttachmentStatus.PROCESSING

    try:
        content = await asyncio.to_thread(_parse_sync, record.detected_mime_type, raw_content)
        record.content = content
        record.content_type = content.content_type
        record.tables_count = len(content.tables)

        # Vision para imágenes y PDFs escaneados
        if vision_enabled and llm is not None:
            if content.content_type == AttachmentContentType.IMAGE:
                log.info("attachment.vision_start", attachment_id=record.attachment_id)
                vision_text = await llm.read_image(raw_content, record.detected_mime_type, _VISION_INSTRUCTION)
                content.vision_description = vision_text
                record.vision_used = True
                log.info("attachment.vision_complete", attachment_id=record.attachment_id, chars=len(vision_text))

            elif (
                content.content_type == AttachmentContentType.DOCUMENT
                and not content.text_blocks
                and content.parse_error
                and record.detected_mime_type == "application/pdf"
            ):
                # PDF escaneado: renderizar primeras páginas y usar Vision
                try:
                    from mia.modules.rrhh.curriculums.indexer import render_pdf_pages  # noqa: PLC0415
                    pages = await asyncio.to_thread(render_pdf_pages, raw_content, 3)
                    descriptions = []
                    for i, page_img in enumerate(pages, 1):
                        desc = await llm.read_image(page_img, "image/png", _SCANNED_PDF_INSTRUCTION)
                        descriptions.append(f"[Página {i}]\n{desc}")
                        record.vision_used = True
                    from mia.attachments.model import TextBlock  # noqa: PLC0415
                    content.text_blocks = [
                        TextBlock(text=d, source_ref=f"page={i}") for i, d in enumerate(descriptions, 1)
                    ]
                    content.vision_description = "\n\n".join(descriptions)
                except Exception as exc:  # noqa: BLE001
                    log.warning("attachment.vision_pdf_failed", error=str(exc))

        record.status = AttachmentStatus.READY
        record.classification = classify_data(record.original_filename, record.content_type)
        record.parser_used = _parser_name(record.detected_mime_type)

    except Exception as exc:  # noqa: BLE001
        log.error("attachment.processing_failed", attachment_id=record.attachment_id, error=str(exc))
        record.status = AttachmentStatus.ERROR
        record.error_message = str(exc)

    record.processing_duration_ms = int((time.perf_counter() - started) * 1000)
    return record


def _parse_sync(mime: str, content: bytes) -> AttachmentContent:
    from mia.attachments.parsers import parse_csv, parse_docx, parse_excel, parse_image, parse_pdf  # noqa: PLC0415

    if mime == "application/pdf":
        return parse_pdf(content)
    if mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return parse_docx(content)
    if mime in ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/vnd.ms-excel"):
        return parse_excel(content)
    if mime in ("text/csv", "application/csv", "text/x-csv"):
        return parse_csv(content)
    if mime in ("image/png", "image/jpeg", "image/webp"):
        return parse_image(content)
    if mime in ("text/plain", "text/markdown", "text/x-markdown"):
        from mia.attachments.model import AttachmentContentType, TextBlock  # noqa: PLC0415
        text = content.decode("utf-8", errors="replace")
        return AttachmentContent(
            content_type=AttachmentContentType.DOCUMENT,
            text_blocks=[TextBlock(text=text, source_ref="full")],
        )
    raise ValueError(f"Tipo MIME no soportado: {mime}")


def _parser_name(mime: str) -> str:
    _map = {
        "application/pdf": "pypdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "python-docx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "openpyxl",
        "application/vnd.ms-excel": "openpyxl",
        "text/csv": "csv",
        "application/csv": "csv",
        "image/png": "pillow+vision",
        "image/jpeg": "pillow+vision",
        "image/webp": "pillow+vision",
    }
    return _map.get(mime, "text")


def build_attachment_context(record: AttachmentRecord) -> str:
    """Genera una descripción compacta del adjunto para inyectar como contexto al LLM."""
    content = record.content
    if content is None:
        return f"[Adjunto: {record.original_filename} (attachment_id: {record.attachment_id}) — no procesado]"

    parts: list[str] = [
        f"## Adjunto: {record.original_filename}",
        # El id va en su propia línea, sin nada más -- ni una nota al lado ni un "←" pegado al
        # valor con solo un par de espacios de separación (como antes). Visto como texto plano
        # por un LLM, no hay frontera clara entre "valor" y "anotación humana" en ese formato, y
        # se reprodujo en preprod (2026-10-25) un adjunto_id real con un "←" colado al final,
        # copiado literalmente de aquí -- el motivo por el que ninguna herramienta lo encontraba.
        f"attachment_id: {record.attachment_id}",
        "Usa EXACTAMENTE ese valor (nunca el nombre del fichero) en cualquier herramienta que "
        "pida 'attachment_id' o 'adjunto_id'.",
    ]

    if content.content_type == AttachmentContentType.IMAGE:
        if content.vision_description:
            parts.append(content.vision_description)
        else:
            w = content.metadata.get("width", "?")
            h = content.metadata.get("height", "?")
            parts.append(f"Imagen {content.metadata.get('format', '')} {w}×{h} px.")
            parts.append("(Pendiente de análisis visual)")

    elif content.content_type == AttachmentContentType.DOCUMENT:
        pc = content.metadata.get("page_count", 0)
        if pc:
            parts.append(f"Documento de {pc} página(s).")
        if content.text_blocks:
            # Primeros ~1500 caracteres de texto
            preview = content.full_text[:1500]
            if len(content.full_text) > 1500:
                preview += f"\n… ({len(content.text_blocks)} bloques de texto en total)"
            parts.append(preview)
        if content.tables:
            parts.append(f"Contiene {len(content.tables)} tabla(s).")
        if content.parse_error:
            parts.append(f"Nota: {content.parse_error}")

    elif content.content_type == AttachmentContentType.DATASET:
        sc = len(content.sheets)
        tr = content.total_rows
        parts.append(f"Dataset con {sc} hoja(s) y {tr} fila(s) en total.")
        for s in content.sheets[:3]:
            parts.append(f"  • Hoja «{s.name}»: {s.row_count} filas, columnas: {', '.join(s.headers[:8])}")
        if sc > 3:
            parts.append(f"  … y {sc - 3} hoja(s) más.")

    return "\n".join(parts)


def get_attachment_summary(record: AttachmentRecord) -> dict[str, Any]:
    """Resumen para el LLM en la respuesta de herramienta."""
    content = record.content
    base: dict[str, Any] = {
        "attachment_id": record.attachment_id,
        "filename": record.original_filename,
        "type": record.content_type.value if record.content_type else "unknown",
        "size_kb": round(record.size_bytes / 1024, 1),
        "status": record.status.value,
    }
    if content:
        if content.content_type == AttachmentContentType.IMAGE and content.vision_description:
            base["description"] = content.vision_description[:500]
        elif content.content_type == AttachmentContentType.DOCUMENT:
            base["page_count"] = content.page_count
            base["text_length"] = len(content.full_text)
            base["tables"] = len(content.tables)
        elif content.content_type == AttachmentContentType.DATASET:
            base["sheet_count"] = content.sheet_count
            base["total_rows"] = content.total_rows
            base["sheets"] = [{"name": s.name, "rows": s.row_count, "cols": len(s.headers)} for s in content.sheets]
    return base

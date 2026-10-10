"""Herramientas de adjuntos para el registro de tools de mIA.

Permiten al LLM consultar el contenido de archivos adjuntos de la conversación.
El LLM decide cuándo llamar a estas herramientas; los cálculos son deterministas.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mia.attachments.dataset import dataset_info, dataset_query, extract_column
from mia.attachments.intelligence import get_attachment_summary
from mia.attachments.model import AttachmentContentType, get_active_refs
from mia.conversation.tools import ToolContext, ToolResult, ToolStatus


class ListAttachmentsParams(BaseModel):
    pass


class ReadAttachmentParams(BaseModel):
    attachment_id: str = Field(description="ID del adjunto a leer")
    section: str = Field(default="", description="Sección o página específica, ej: 'page=3' o 'heading=Conclusiones'")
    max_chars: int = Field(default=2000, ge=100, le=8000, description="Máximo de caracteres a devolver")


class DatasetInfoParams(BaseModel):
    attachment_id: str = Field(description="ID del adjunto con datos estructurados (Excel/CSV)")


class DatasetQueryParams(BaseModel):
    attachment_id: str = Field(description="ID del adjunto Excel o CSV")
    sheet_name: str | None = Field(default=None, description="Nombre de la hoja (vacío = primera hoja)")
    filter_col: str | None = Field(default=None, description="Columna por la que filtrar")
    filter_value: str | None = Field(default=None, description="Valor a buscar en filter_col")
    group_by: str | None = Field(default=None, description="Columna por la que agrupar")
    aggregate: str | None = Field(
        default=None, description="Función de agregación: count, sum, avg"
    )
    agg_col: str | None = Field(default=None, description="Columna numérica para sum/avg")
    limit: int = Field(default=50, ge=1, le=500, description="Máximo de filas/grupos a devolver")


class ExtractColumnParams(BaseModel):
    attachment_id: str = Field(description="ID del adjunto Excel o CSV")
    column_name: str = Field(description="Nombre de la columna cuyos valores únicos se extraen")
    sheet_name: str | None = Field(default=None)


async def handle_list_attachments(
    params: ListAttachmentsParams,
    ctx: ToolContext,
) -> ToolResult:
    svc = ctx.attachment_service
    if svc is None:
        return ToolResult(ToolStatus.SOURCE_UNAVAILABLE, "La funcionalidad de adjuntos no está activa.")

    refs = get_active_refs(ctx.session_state)
    if not refs:
        return ToolResult(ToolStatus.NOT_FOUND, "No hay adjuntos en esta conversación.")

    summaries = []
    for ref in refs:
        record = svc.get_for_user(ref.attachment_id, ctx.user.user_id)
        if record:
            summaries.append(get_attachment_summary(record))
        else:
            summaries.append({
                "attachment_id": ref.attachment_id,
                "filename": ref.filename,
                "status": "no_disponible",
            })

    return ToolResult.ok({"adjuntos": summaries, "total": len(summaries)})


async def handle_read_attachment(
    params: ReadAttachmentParams,
    ctx: ToolContext,
) -> ToolResult:
    svc = ctx.attachment_service
    if svc is None:
        return ToolResult(ToolStatus.SOURCE_UNAVAILABLE, "La funcionalidad de adjuntos no está activa.")

    record = svc.get_for_user(params.attachment_id, ctx.user.user_id)
    if record is None:
        return ToolResult(ToolStatus.NOT_FOUND, f"Adjunto {params.attachment_id} no encontrado o expirado.")

    from mia.diagnostics import EventStage, emit as diag_emit  # noqa: PLC0415
    diag_emit(EventStage.ATTACHMENT_RETRIEVAL, data={
        "attachment_id": params.attachment_id,
        "section": params.section,
    })

    content = record.content
    if content is None:
        return ToolResult(ToolStatus.ERROR, "El adjunto no ha sido procesado todavía.")

    if content.content_type == AttachmentContentType.IMAGE:
        desc = content.vision_description or "Imagen recibida, pendiente de análisis visual."
        return ToolResult.ok({"tipo": "imagen", "descripcion": desc[:params.max_chars], "filename": record.original_filename})

    if content.content_type == AttachmentContentType.DATASET:
        info = dataset_info(content)
        return ToolResult.ok({"tipo": "dataset", "filename": record.original_filename, **info})

    # Documento: devolver texto relevante
    section = params.section.strip()
    blocks = content.text_blocks

    if section:
        # Filtrar bloques que coincidan con la referencia pedida
        matching = [b for b in blocks if section.lower() in b.source_ref.lower()]
        if matching:
            blocks = matching

    text = "\n\n".join(b.text for b in blocks)
    if len(text) > params.max_chars:
        text = text[: params.max_chars] + f"\n… (texto recortado, {len(content.full_text)} caracteres en total)"

    tables_summary: list[dict[str, Any]] = []
    for t in content.tables[:5]:
        tables_summary.append({
            "headers": t.headers,
            "rows_preview": t.rows[:3],
            "total_rows": len(t.rows),
            "source_ref": t.source_ref,
        })

    return ToolResult.ok({
        "tipo": "documento",
        "filename": record.original_filename,
        "page_count": content.page_count,
        "text": text,
        "tables": tables_summary,
    })


async def handle_dataset_info(
    params: DatasetInfoParams,
    ctx: ToolContext,
) -> ToolResult:
    svc = ctx.attachment_service
    if svc is None:
        return ToolResult(ToolStatus.SOURCE_UNAVAILABLE, "La funcionalidad de adjuntos no está activa.")

    record = svc.get_for_user(params.attachment_id, ctx.user.user_id)
    if record is None:
        return ToolResult(ToolStatus.NOT_FOUND, f"Adjunto {params.attachment_id} no encontrado.")

    content = record.content
    if content is None or content.content_type != AttachmentContentType.DATASET:
        return ToolResult(ToolStatus.ERROR, "El adjunto no contiene datos estructurados (Excel/CSV).")

    from mia.diagnostics import EventStage, emit as diag_emit  # noqa: PLC0415
    diag_emit(EventStage.ATTACHMENT_DATASET_QUERY, data={"op": "info", "attachment_id": params.attachment_id})

    info = dataset_info(content)
    info["filename"] = record.original_filename
    return ToolResult.ok(info)


async def handle_dataset_query(
    params: DatasetQueryParams,
    ctx: ToolContext,
) -> ToolResult:
    svc = ctx.attachment_service
    if svc is None:
        return ToolResult(ToolStatus.SOURCE_UNAVAILABLE, "La funcionalidad de adjuntos no está activa.")

    record = svc.get_for_user(params.attachment_id, ctx.user.user_id)
    if record is None:
        return ToolResult(ToolStatus.NOT_FOUND, f"Adjunto {params.attachment_id} no encontrado.")

    content = record.content
    if content is None or content.content_type != AttachmentContentType.DATASET:
        return ToolResult(ToolStatus.ERROR, "El adjunto no contiene datos estructurados.")

    from mia.diagnostics import EventStage, emit as diag_emit  # noqa: PLC0415
    diag_emit(EventStage.ATTACHMENT_DATASET_QUERY, data={
        "op": "query",
        "attachment_id": params.attachment_id,
        "sheet": params.sheet_name,
        "filter_col": params.filter_col,
        "group_by": params.group_by,
    })

    result = dataset_query(
        content,
        sheet_name=params.sheet_name,
        filter_col=params.filter_col,
        filter_value=params.filter_value,
        group_by=params.group_by,
        aggregate=params.aggregate,
        agg_col=params.agg_col,
        limit=params.limit,
    )
    return ToolResult.ok(result)


async def handle_extract_column(
    params: ExtractColumnParams,
    ctx: ToolContext,
) -> ToolResult:
    svc = ctx.attachment_service
    if svc is None:
        return ToolResult(ToolStatus.SOURCE_UNAVAILABLE, "La funcionalidad de adjuntos no está activa.")

    record = svc.get_for_user(params.attachment_id, ctx.user.user_id)
    if record is None:
        return ToolResult(ToolStatus.NOT_FOUND, f"Adjunto {params.attachment_id} no encontrado.")

    content = record.content
    if content is None or content.content_type != AttachmentContentType.DATASET:
        return ToolResult(ToolStatus.ERROR, "El adjunto no contiene datos estructurados.")

    values = extract_column(content, params.column_name, params.sheet_name)
    return ToolResult.ok({
        "column": params.column_name,
        "values": values[:200],
        "total": len(values),
    })


def register(registry: Any, attachment_service: Any) -> None:
    """Registra las herramientas de adjuntos en el ToolRegistry cuando están habilitadas."""
    from mia.conversation.tools import Tool  # noqa: PLC0415

    registry.register(Tool(
        name="listar_adjuntos",
        description=(
            "Lista los archivos adjuntos disponibles en la conversación actual. "
            "Úsalo cuando el usuario mencione 'el archivo', 'el Excel', 'el documento' que subió."
        ),
        params=ListAttachmentsParams,
        handler=handle_list_attachments,
        timeout_seconds=5.0,
    ))

    registry.register(Tool(
        name="leer_adjunto",
        description=(
            "Lee el contenido de un adjunto: texto de un documento PDF/DOCX, "
            "descripción de una imagen, o estructura de un Excel/CSV. "
            "Usa section para solicitar una parte específica (ej: 'page=3', 'heading=Resumen')."
        ),
        params=ReadAttachmentParams,
        handler=handle_read_attachment,
        timeout_seconds=10.0,
    ))

    registry.register(Tool(
        name="info_dataset_adjunto",
        description=(
            "Describe la estructura de un Excel o CSV adjunto: hojas, columnas, tipos y recuento de filas. "
            "Úsalo antes de hacer consultas para saber qué hay disponible."
        ),
        params=DatasetInfoParams,
        handler=handle_dataset_info,
        timeout_seconds=5.0,
    ))

    registry.register(Tool(
        name="consultar_dataset_adjunto",
        description=(
            "Realiza operaciones deterministas sobre un Excel o CSV adjunto: "
            "filtrar filas, agrupar por columna, calcular totales/medias. "
            "No envía todas las filas al LLM: ejecuta el cálculo de forma estructurada."
        ),
        params=DatasetQueryParams,
        handler=handle_dataset_query,
        timeout_seconds=10.0,
    ))

    registry.register(Tool(
        name="extraer_columna_adjunto",
        description=(
            "Extrae los valores únicos de una columna de un Excel o CSV adjunto. "
            "Útil para obtener una lista de personas, departamentos, fechas, etc."
        ),
        params=ExtractColumnParams,
        handler=handle_extract_column,
        timeout_seconds=5.0,
    ))

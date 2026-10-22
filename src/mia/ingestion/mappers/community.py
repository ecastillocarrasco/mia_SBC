"""Transformaciones de listas de SharePoint del dominio Community."""

from __future__ import annotations

from typing import Any

from mia.ingestion.mappers.common import (
    MapContext,
    boolean,
    hyperlink_field,
    number,
    sp_datetime,
    sp_local_date,
    text,
)
from mia.text import plain_text

Row = dict[str, Any]


def newsletter_item(item: dict[str, Any], ctx: MapContext) -> list[Row]:
    order = number(item.get("Orden"))
    body_html = text(item.get("Cuerpo"))
    return [
        {
            "sp_id": int(item["ID"]),
            "title": text(item.get("Title")) or f"Noticia {item['ID']}",
            "summary": text(item.get("Resumen")),
            "body": plain_text(body_html, "html") if body_html else None,
            "category": text(item.get("Categoria")),
            "featured": boolean(item.get("Destacada")),
            "active": boolean(item.get("Activa")),
            "order": int(order) if order is not None else None,
            "expires_at": sp_local_date(item.get("FechaCaducidad"), ctx.tz),
            "image_url": hyperlink_field(item.get("Imagen")),
            "link_url": hyperlink_field(item.get("Enlace")),
            "button_text": text(item.get("TextoBoton")),
            "created_at": sp_datetime(item.get("Created")),
            "modified_at": sp_datetime(item.get("Modified")),
        }
    ]

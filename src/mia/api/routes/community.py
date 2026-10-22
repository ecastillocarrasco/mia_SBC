"""Imágenes de Community servidas desde SharePoint con las credenciales de mIA.

Las URL que guarda ``mia.data.community.NewsletterItem`` (campo «Imagen» de la lista
NewsletterCorporativa) apuntan directamente a SharePoint: el navegador del usuario no tiene
sesión ahí y SharePoint las responde con 403 (verificado). Esta ruta las descarga en el momento
con el certificado de aplicación ya configurado (el mismo que usa la sincronización) y las sirve
como si fueran propias — igual que ``api.routes.documents`` con los documentos de RRHH.
"""

from __future__ import annotations

import mimetypes
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response

from mia.api.deps import ServicesDep, UserDep
from mia.connectors.sharepoint import SharePointError
from mia.data import NewsletterItem

router = APIRouter(prefix="/api/community", tags=["community"])

MAX_IMAGE_BYTES = 10 * 1024 * 1024


@router.get("/newsletter/{item_id}/imagen")
async def newsletter_image(item_id: int, services: ServicesDep, user: UserDep) -> Response:
    del user  # información pública (igual que la propia herramienta, sin Permission asociado)
    if services.sharepoint is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "SharePoint no está configurado")
    async with services.db.session() as db:
        record = await db.get(NewsletterItem, item_id)
    if record is None or not record.image_url:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Esta noticia no tiene imagen")
    path = urlsplit(record.image_url).path
    try:
        content = await services.sharepoint.download(path, MAX_IMAGE_BYTES)
    except SharePointError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "No se ha podido leer la imagen de SharePoint") from exc
    media_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    return Response(content, media_type=media_type, headers={"Cache-Control": "private, max-age=3600"})

"""Mapper de la newsletter corporativa (lista «NewsletterCorporativa» de SharePoint).

Los elementos de ejemplo son formas reales observadas en la lista (verificado en vivo contra
SharePoint en octubre de 2026), no inventadas: Hyperlink/Picture como ``{"Url":..., "Description":...}``,
``Cuerpo`` como HTML enriquecido de Office (clases ``MsoNormal``, ``ExternalClass...``), ``Orden``
como float (columna Number de SharePoint).
"""

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

from mia.ingestion import Pseudonymizer
from mia.ingestion.mappers import community
from mia.ingestion.mappers.common import MapContext

CTX = MapContext(tz=ZoneInfo("Europe/Madrid"), pseudonymize=Pseudonymizer("k"))

_REAL_ITEM = {
    "Id": 1,
    "ID": 1,
    "Title": "Jubilación Blas ",
    "Resumen": "Tras casi cuatro décadas de servicio, nuestro compañero Blas se ha jubilado.",
    "Cuerpo": (
        '<div class="ExternalClass39AAB310"><p class="MsoNormal"><i>Blas ha formado parte de '
        "Sunset Beach Club desde 1987.<br>\n<br>\nGracias por todo.</i></p></div>"
    ),
    "FechaCaducidad": None,
    "Imagen": {
        "Description": "Imagen",
        "Url": "https://sunsetbeachclub.sharepoint.com/.../Blas-photo.png",
    },
    "Categoria": "Corporativa",
    "Destacada": True,
    "Activa": True,
    "Orden": 1.0,
    "Enlace": {
        "Description": "https://sunsetbeachclub.sharepoint.com/.../imgHomeTurnos.png",
        "Url": "https://sunsetbeachclub.sharepoint.com/.../imgHomeTurnos.png",
    },
    "TextoBoton": "Consultar",
    "Modified": "2026-08-19T14:57:09Z",
    "Created": "2026-06-23T19:17:18Z",
}


def test_newsletter_item_maps_the_real_sharepoint_shape() -> None:
    row = community.newsletter_item(_REAL_ITEM, CTX)[0]
    assert row["sp_id"] == 1
    assert row["title"] == "Jubilación Blas"  # texto() recorta espacios
    assert row["summary"].startswith("Tras casi cuatro décadas")
    assert "Blas ha formado parte de Sunset Beach Club desde 1987." in row["body"]
    assert "Gracias por todo." in row["body"]
    assert "<" not in row["body"]  # sin HTML
    assert row["category"] == "Corporativa"
    assert row["featured"] is True
    assert row["active"] is True
    assert row["order"] == 1
    assert row["expires_at"] is None
    assert row["image_url"] == "https://sunsetbeachclub.sharepoint.com/.../Blas-photo.png"
    assert row["link_url"] == "https://sunsetbeachclub.sharepoint.com/.../imgHomeTurnos.png"
    assert row["button_text"] == "Consultar"
    assert row["created_at"] is not None and row["created_at"].year == 2026


def test_newsletter_item_without_expiration_fields_survive() -> None:
    row = community.newsletter_item(
        {
            "ID": 2,
            "Title": "Sin caducidad ni enlace",
            "Resumen": None,
            "Cuerpo": None,
            "FechaCaducidad": "2026-12-31T00:00:00Z",
            "Imagen": None,
            "Categoria": None,
            "Destacada": False,
            "Activa": False,
            "Orden": None,
            "Enlace": None,
            "TextoBoton": None,
            "Created": None,
            "Modified": None,
        },
        CTX,
    )[0]
    assert row["title"] == "Sin caducidad ni enlace"
    assert row["summary"] is None
    assert row["body"] is None
    assert row["active"] is False
    assert row["order"] is None
    assert row["expires_at"] == date(2026, 12, 31)
    assert row["image_url"] is None
    assert row["link_url"] is None

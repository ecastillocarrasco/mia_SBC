"""``GET /api/community/newsletter/{id}/imagen``.

La URL que guarda SharePoint (campo «Imagen» de NewsletterCorporativa) responde 403 sin sesión de
SharePoint en el navegador (verificado contra el sitio real) — por eso esta ruta descarga la
imagen con las credenciales de aplicación de mIA y la sirve ella misma, igual que ya hace
``api.routes.documents`` con nóminas y documentos firmados."""

from __future__ import annotations

import httpx

from mia.api.services import Services
from mia.auth.providers import DevIdentityProvider
from mia.connectors.sharepoint import SharePointClient, StaticTokenProvider
from mia.data import Database, NewsletterItem
from mia.settings import AuthSettings

PNG_MAGIC = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def _mock_sharepoint() -> SharePointClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=PNG_MAGIC)

    return SharePointClient(
        site_url="https://sunsetbeachclub.sharepoint.com/sites/PortalCorporativo/RRHH",
        tokens=StaticTokenProvider(),
        transport=httpx.MockTransport(handler),
    )


async def _seed(db: Database, *, image_url: str | None) -> None:
    async with db.session() as s:
        s.add(
            NewsletterItem(
                sp_id=1, title="Jubilación Blas", summary="Resumen", body="Cuerpo",
                category="Corporativa", featured=False, active=True, order=1,
                image_url=image_url, link_url=None, button_text=None,
            )
        )


async def test_serves_the_image_through_mias_own_credentials(client: httpx.AsyncClient, services: Services) -> None:
    await _seed(
        services.db,
        image_url="https://sunsetbeachclub.sharepoint.com/sites/PortalCorporativo/RRHH/Documents/x/blas.png",
    )
    services.sharepoint = _mock_sharepoint()
    services.identity = DevIdentityProvider(AuthSettings(dev_user_id="u1", dev_roles=["mia.admin"]))

    response = await client.get("/api/community/newsletter/1/imagen")

    assert response.status_code == 200
    assert response.content == PNG_MAGIC
    assert response.headers["content-type"] == "image/png"


async def test_404_when_the_item_has_no_image(client: httpx.AsyncClient, services: Services) -> None:
    await _seed(services.db, image_url=None)
    services.sharepoint = _mock_sharepoint()
    services.identity = DevIdentityProvider(AuthSettings(dev_user_id="u1", dev_roles=["mia.admin"]))

    response = await client.get("/api/community/newsletter/1/imagen")

    assert response.status_code == 404


async def test_404_when_the_item_does_not_exist(client: httpx.AsyncClient, services: Services) -> None:
    services.sharepoint = _mock_sharepoint()
    services.identity = DevIdentityProvider(AuthSettings(dev_user_id="u1", dev_roles=["mia.admin"]))

    response = await client.get("/api/community/newsletter/999/imagen")

    assert response.status_code == 404


async def test_503_when_sharepoint_is_not_configured(client: httpx.AsyncClient, services: Services) -> None:
    await _seed(services.db, image_url="https://x.test/a.png")
    services.sharepoint = None
    services.identity = DevIdentityProvider(AuthSettings(dev_user_id="u1", dev_roles=["mia.admin"]))

    response = await client.get("/api/community/newsletter/1/imagen")

    assert response.status_code == 503

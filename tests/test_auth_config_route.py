"""``GET /api/auth/config``: lo único que el front-end necesita saber ANTES de que exista sesión
para decidir si mostrar la pantalla de login de Entra ID (MSAL.js) y con qué tenant/client_id."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from mia.api.services import Services
from mia.auth.providers import DevIdentityProvider
from mia.llm.fake import FakeLLMProvider, final_answer
from mia.main import create_app
from mia.settings import AuthMode, AuthSettings
from mia.voice import CachedVoice, NullVoiceProvider
from tests.conftest import make_settings
from tests.dbutil import fresh_database


async def test_dev_mode_does_not_require_login(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/auth/config")
    assert response.status_code == 200
    body = response.json()
    assert body == {"mode": "dev", "requires_login": False, "entra": None}


@pytest.fixture
async def entra_client(tmp_path: Path) -> httpx.AsyncClient:
    settings = make_settings(
        tmp_path,
        auth={"mode": AuthMode.ENTRA, "entra_tenant_id": "tenant-123", "entra_client_id": "client-456",
              "entra_web_client_id": "web-123", "entra_desktop_client_id": "desktop-456"},
    )
    db = await fresh_database(tmp_path)
    llm = FakeLLMProvider(lambda req: final_answer("ok", "ok"))
    services = Services.build(settings, llm=llm, db=db, voice=CachedVoice(NullVoiceProvider()))
    app = create_app(settings, services=services)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            yield http
    await services.aclose()


async def test_entra_mode_exposes_tenant_and_client_id(entra_client: httpx.AsyncClient) -> None:
    response = await entra_client.get("/api/auth/config")
    assert response.status_code == 200
    assert response.json() == {
        "mode": "entra",
        "requires_login": True,
        "entra": {"tenant_id": "tenant-123", "client_id": "client-456", "web_client_id": "web-123",
                  "desktop_client_id": "desktop-456", "scope": "api://client-456/access_as_user"},
    }


async def test_auth_config_is_public_no_token_required(entra_client: httpx.AsyncClient) -> None:
    """Necesario precisamente porque no hay sesión todavía: nunca debe exigir Authorization."""
    response = await entra_client.get("/api/auth/config")
    assert response.status_code == 200


async def test_explicit_entra_scope_overrides_the_default(tmp_path: Path) -> None:
    settings = make_settings(
        tmp_path,
        auth={
            "mode": AuthMode.ENTRA,
            "entra_tenant_id": "tenant-123",
            "entra_client_id": "client-456",
            "entra_web_client_id": "web-123",
            "entra_desktop_client_id": "desktop-456",
            "entra_scope": "api://client-456/access_as_user",
        },
    )
    db = await fresh_database(tmp_path)
    llm = FakeLLMProvider(lambda req: final_answer("ok", "ok"))
    services = Services.build(settings, llm=llm, db=db, voice=CachedVoice(NullVoiceProvider()))
    app = create_app(settings, services=services)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            response = await http.get("/api/auth/config")
    await services.aclose()
    assert response.json()["entra"]["scope"] == "api://client-456/access_as_user"


# ------------------------------------------------------------------ GET /api/auth/me
async def test_me_reports_access_for_a_role_with_permissions(client: httpx.AsyncClient) -> None:
    """Autenticación (login) y autorización (algún permiso) son cosas distintas: este endpoint
    es la única forma de que el front-end sepa la segunda antes de dejar usar mIA."""
    response = await client.get("/api/auth/me")
    assert response.status_code == 200
    body = response.json()
    assert body["has_access"] is True
    assert body["user_id"] and body["display_name"]


async def test_me_reports_no_access_for_an_unrecognized_role(client: httpx.AsyncClient, services: Services) -> None:
    """Un token válido con un rol que no existe en ROLE_PERMISSIONS (typo, App Role sin asignar...)
    autentica correctamente pero no da ningún permiso: has_access debe ser False, no un 403."""
    services.identity = DevIdentityProvider(AuthSettings(dev_user_id="sin-rol", dev_roles=["no.such.role"]))
    response = await client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json()["has_access"] is False

"""Acceso al panel de diagnóstico (``/api/admin/diagnostics/*``).

Root cause de la versión anterior de este fix: una navegación directa del navegador nunca puede
adjuntar una cabecera ``Authorization: Bearer`` (no hay contexto JS antes de que la petición
salga), así que gatear el panel tras el mismo mecanismo que el resto de la app (Entra ID) lo
dejaba estructuralmente inalcanzable -- bucle de login. Decisión final: en vez de reutilizar
``Permission``/Entra ID, esta ruta usa HTTP Basic Auth contra una lista cerrada de 3 emails
(``settings.diagnostics.admin_users``) con una contraseña compartida (``admin_password``) --
el navegador negocia Basic Auth solo, con un diálogo nativo, en cualquier navegación directa,
``fetch`` o ``EventSource`` posterior al mismo origen, sin tokens que copiar/pegar ni lógica
adicional en el HTML del panel.
"""

from __future__ import annotations

import base64
from pathlib import Path

import httpx
import pytest

from mia.api.services import Services
from mia.llm.fake import FakeLLMProvider, final_answer
from mia.main import create_app
from mia.voice import CachedVoice, NullVoiceProvider
from tests.conftest import make_settings
from tests.dbutil import fresh_database

ALLOWED_EMAILS = ["nominas@sunsetbeachclub.com", "e.castillo@sunsetbeachclub.com", "m.fernandez@sunsetbeachclub.com"]
PASSWORD = "contraseña-de-prueba"


def _basic_header(username: str, password: str) -> dict[str, str]:
    raw = f"{username}:{password}".encode()
    return {"Authorization": f"Basic {base64.b64encode(raw).decode()}"}


@pytest.fixture
async def diagnostics_client(tmp_path: Path) -> httpx.AsyncClient:
    settings = make_settings(
        tmp_path,
        diagnostics={"enabled": True, "admin_users": ALLOWED_EMAILS, "admin_password": PASSWORD},
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


# ── Settings: sin admin_users/admin_password, diagnostics no debe arrancar ───


def test_settings_reject_diagnostics_enabled_without_admin_credentials(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="ADMIN_USERS"):
        make_settings(tmp_path, diagnostics={"enabled": True})


def test_settings_reject_diagnostics_enabled_with_users_but_no_password(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="ADMIN_USERS"):
        make_settings(tmp_path, diagnostics={"enabled": True, "admin_users": ALLOWED_EMAILS})


def test_settings_accept_diagnostics_disabled_without_admin_credentials(tmp_path: Path) -> None:
    make_settings(tmp_path, diagnostics={"enabled": False})  # no debe lanzar


# ── /  (panel HTML) y endpoints de datos: todos exigen Basic Auth real ───────

ALL_PATHS = [
    "/api/admin/diagnostics/",
    "/api/admin/diagnostics/status",
    "/api/admin/diagnostics/traces",
    "/api/admin/diagnostics/metrics",
    "/api/admin/diagnostics/live",
]


@pytest.mark.parametrize("path", ALL_PATHS)
async def test_rejects_without_any_credentials(diagnostics_client: httpx.AsyncClient, path: str) -> None:
    response = await diagnostics_client.get(path)
    assert response.status_code == 401
    assert response.headers["www-authenticate"].lower().startswith("basic")


@pytest.mark.parametrize("path", ALL_PATHS)
async def test_rejects_email_not_in_the_allowed_list(diagnostics_client: httpx.AsyncClient, path: str) -> None:
    response = await diagnostics_client.get(path, headers=_basic_header("intruso@sunsetbeachclub.com", PASSWORD))
    assert response.status_code == 401


@pytest.mark.parametrize("path", ALL_PATHS)
async def test_rejects_allowed_email_with_wrong_password(diagnostics_client: httpx.AsyncClient, path: str) -> None:
    response = await diagnostics_client.get(path, headers=_basic_header(ALLOWED_EMAILS[0], "contraseña-equivocada"))
    assert response.status_code == 401


@pytest.mark.parametrize("email", ALLOWED_EMAILS)
async def test_panel_html_accepts_any_of_the_three_allowed_emails(
    diagnostics_client: httpx.AsyncClient, email: str
) -> None:
    response = await diagnostics_client.get("/api/admin/diagnostics/", headers=_basic_header(email, PASSWORD))
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


async def test_email_comparison_is_case_insensitive(diagnostics_client: httpx.AsyncClient) -> None:
    response = await diagnostics_client.get(
        "/api/admin/diagnostics/", headers=_basic_header(ALLOWED_EMAILS[0].upper(), PASSWORD)
    )
    assert response.status_code == 200


async def test_status_endpoint_with_valid_credentials_returns_data(diagnostics_client: httpx.AsyncClient) -> None:
    response = await diagnostics_client.get(
        "/api/admin/diagnostics/status", headers=_basic_header(ALLOWED_EMAILS[1], PASSWORD)
    )
    assert response.status_code == 200
    assert response.json()["diagnostics_enabled"] is True


async def test_panel_html_still_404_when_diagnostics_disabled(tmp_path: Path) -> None:
    """``_require_enabled()`` debe comprobarse incluso con credenciales válidas -- no basta con
    que el 404 ocurra "antes" de la auth, porque ya no hay ningún camino sin auth en absoluto.

    ``mia.diagnostics._store`` es un singleton a nivel de módulo que ``create_app`` solo
    inicializa (nunca lo resetea a ``None`` al cerrar, ver ``main.py`` lifespan) -- se resetea
    aquí explícitamente antes y después, igual que ``tests/test_diagnostics.py``, para no
    depender de qué test con diagnostics habilitado corrió antes en el mismo proceso."""
    import mia.diagnostics as d

    original_store, original_broadcaster = d._store, d._broadcaster
    d._store, d._broadcaster = None, None
    try:
        # admin_users/admin_password se fijan igualmente (el validador solo los exige cuando
        # enabled=True, no prohíbe tenerlos con enabled=False) para probar con credenciales
        # válidas: la comprobación de _require_enabled() va DESPUÉS de la dependencia de auth,
        # así que sin credenciales esto daría 401 antes de llegar a comprobar si está habilitado
        # -- lo relevante aquí es que, incluso autenticado correctamente, sigue dando 404.
        settings = make_settings(
            tmp_path,
            diagnostics={"enabled": False, "admin_users": ALLOWED_EMAILS, "admin_password": PASSWORD},
        )
        db = await fresh_database(tmp_path)
        llm = FakeLLMProvider(lambda req: final_answer("ok", "ok"))
        services = Services.build(settings, llm=llm, db=db, voice=CachedVoice(NullVoiceProvider()))
        app = create_app(settings, services=services)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                response = await http.get("/api/admin/diagnostics/", headers=_basic_header(ALLOWED_EMAILS[0], PASSWORD))
        await services.aclose()
        assert response.status_code == 404
    finally:
        d._store, d._broadcaster = original_store, original_broadcaster

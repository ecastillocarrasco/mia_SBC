from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest

from mia.api.services import Services
from mia.auth import Permission, UserContext
from mia.auth.providers import AuthenticationError, DevIdentityProvider, EasyAuthIdentityProvider
from mia.settings import AuthMode, AuthSettings, Environment
from tests.conftest import make_settings


class _Request:
    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = headers


def _principal(claims: list[dict[str, str]]) -> str:
    return base64.b64encode(json.dumps({"claims": claims, "role_typ": "roles"}).encode()).decode()


def test_roles_map_to_permissions() -> None:
    user = UserContext("u", "U", roles=frozenset({"mia.responsable"}))
    assert user.has(Permission.TURNOS_LEER)
    assert not user.has(Permission.NOMINAS_LEER)
    assert user.has(None)


async def test_easyauth_reads_platform_identity() -> None:
    header = _principal(
        [
            {"typ": "http://schemas.microsoft.com/identity/claims/objectidentifier", "val": "oid-1"},
            {"typ": "name", "val": "Enrique"},
            {"typ": "preferred_username", "val": "enrique@example.com"},
            {"typ": "roles", "val": "mia.rrhh"},
        ]
    )
    user = await EasyAuthIdentityProvider().authenticate(_Request({"x-ms-client-principal": header}))  # type: ignore[arg-type]
    assert user.user_id == "oid-1"
    assert user.display_name == "Enrique"
    assert user.has(Permission.NOMINAS_LEER)


async def test_easyauth_without_identity_is_rejected() -> None:
    with pytest.raises(AuthenticationError):
        await EasyAuthIdentityProvider().authenticate(_Request({}))  # type: ignore[arg-type]


def test_dev_auth_is_forbidden_in_production(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no está permitido en producción"):
        make_settings(tmp_path, environment=Environment.PRODUCTION, auth={"mode": AuthMode.DEV})


async def test_session_belongs_to_its_owner(client: httpx.AsyncClient, services: object) -> None:
    assert isinstance(services, Services)
    session_id = (await client.post("/api/chat", json={"message": "hola"})).json()["session_id"]
    services.identity = DevIdentityProvider(AuthSettings(dev_user_id="otra-persona"))
    response = await client.post("/api/chat", json={"message": "hola", "session_id": session_id})
    assert response.status_code == 403

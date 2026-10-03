from __future__ import annotations

import base64
import json
import time
from pathlib import Path

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from mia.api.services import Services
from mia.auth import Permission, UserContext
from mia.auth.providers import (
    AuthenticationError,
    DevIdentityProvider,
    EasyAuthIdentityProvider,
    EntraIdIdentityProvider,
)
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


# ------------------------------------------------------------------ entra (MSAL / Entra ID)
TENANT = "11111111-1111-1111-1111-111111111111"
CLIENT_ID = "22222222-2222-2222-2222-222222222222"
_RSA_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_KID = "test-kid-1"


def _jwks_response(request: httpx.Request) -> httpx.Response:
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(_RSA_KEY.public_key()))
    jwk["kid"] = _KID
    return httpx.Response(200, json={"keys": [jwk]})


def _entra_provider() -> EntraIdIdentityProvider:
    settings = AuthSettings(mode=AuthMode.ENTRA, entra_tenant_id=TENANT, entra_client_id=CLIENT_ID)
    client = httpx.AsyncClient(transport=httpx.MockTransport(_jwks_response))
    return EntraIdIdentityProvider(settings, http_client=client)


def _entra_token(**overrides: object) -> str:
    now = int(time.time())
    claims: dict[str, object] = {
        "oid": "oid-1",
        "name": "Enrique",
        "preferred_username": "enrique@example.com",
        "roles": ["mia.rrhh"],
        "aud": CLIENT_ID,
        "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
        "iat": now,
        "exp": now + 3600,
        **overrides,
    }
    return jwt.encode(claims, _RSA_KEY, algorithm="RS256", headers={"kid": _KID})


async def test_entra_token_maps_to_user_and_permissions() -> None:
    user = await _entra_provider().authenticate(_Request({"authorization": f"Bearer {_entra_token()}"}))  # type: ignore[arg-type]
    assert user.user_id == "oid-1"
    assert user.display_name == "Enrique"
    assert user.email == "enrique@example.com"
    assert user.has(Permission.NOMINAS_LEER)  # mia.rrhh


async def test_entra_without_header_is_rejected() -> None:
    with pytest.raises(AuthenticationError):
        await _entra_provider().authenticate(_Request({}))  # type: ignore[arg-type]


async def test_entra_wrong_audience_is_rejected() -> None:
    token = _entra_token(aud="otra-aplicacion")
    with pytest.raises(AuthenticationError):
        await _entra_provider().authenticate(_Request({"authorization": f"Bearer {token}"}))  # type: ignore[arg-type]


async def test_entra_wrong_issuer_is_rejected() -> None:
    token = _entra_token(iss="https://login.microsoftonline.com/otro-tenant/v2.0")
    with pytest.raises(AuthenticationError):
        await _entra_provider().authenticate(_Request({"authorization": f"Bearer {token}"}))  # type: ignore[arg-type]


async def test_entra_expired_token_is_rejected() -> None:
    token = _entra_token(exp=int(time.time()) - 60)
    with pytest.raises(AuthenticationError):
        await _entra_provider().authenticate(_Request({"authorization": f"Bearer {token}"}))  # type: ignore[arg-type]


async def test_entra_token_signed_by_an_untrusted_key_is_rejected() -> None:
    """Confusión de clave: firmado con una clave que el tenant no tiene en su JWKS."""
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = int(time.time())
    token = jwt.encode(
        {
            "oid": "oid-1",
            "aud": CLIENT_ID,
            "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
            "iat": now,
            "exp": now + 3600,
        },
        other_key,
        algorithm="RS256",
        headers={"kid": "otro-kid-no-en-el-jwks"},
    )
    with pytest.raises(AuthenticationError):
        await _entra_provider().authenticate(_Request({"authorization": f"Bearer {token}"}))  # type: ignore[arg-type]


def test_dev_auth_is_forbidden_in_production(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no está permitido en producción"):
        make_settings(tmp_path, environment=Environment.PRODUCTION, auth={"mode": AuthMode.DEV})


async def test_session_belongs_to_its_owner(client: httpx.AsyncClient, services: object) -> None:
    assert isinstance(services, Services)
    session_id = (await client.post("/api/chat", json={"message": "hola"})).json()["session_id"]
    services.identity = DevIdentityProvider(AuthSettings(dev_user_id="otra-persona"))
    response = await client.post("/api/chat", json={"message": "hola", "session_id": session_id})
    assert response.status_code == 403

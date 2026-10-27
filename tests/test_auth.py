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


# ------------------------------------------------------------------ App Roles reales de Entra ID
def test_global_app_role_has_every_permission() -> None:
    user = UserContext("u", "U", roles=frozenset({"Global"}))
    assert user.permissions == frozenset(Permission)


def test_rrhh_app_role_matches_the_dev_equivalent() -> None:
    """ "RRHH" (App Role real) y "mia.rrhh" (rol de desarrollo) deben dar exactamente el mismo
    acceso: son el mismo conjunto de permisos bajo dos nombres, nunca dos definiciones que puedan
    divergir en silencio."""
    rrhh = UserContext("u", "U", roles=frozenset({"RRHH"}))
    dev_rrhh = UserContext("u", "U", roles=frozenset({"mia.rrhh"}))
    assert rrhh.permissions == dev_rrhh.permissions


def test_rrhh_no_nominas_app_role_excludes_only_nominas() -> None:
    con_nominas = UserContext("u", "U", roles=frozenset({"RRHH"}))
    sin_nominas = UserContext("u", "U", roles=frozenset({"RRHH.NoNominas"}))
    assert sin_nominas.has(Permission.EMPLEADOS_LEER)
    assert sin_nominas.has(Permission.DOCUMENTOS_CONTENIDO)
    assert not sin_nominas.has(Permission.NOMINAS_LEER)
    assert not sin_nominas.has(Permission.NOMINAS_IMPORTES)
    # La única diferencia entre ambos roles son los dos permisos de nóminas.
    assert con_nominas.permissions - sin_nominas.permissions == {
        Permission.NOMINAS_LEER,
        Permission.NOMINAS_IMPORTES,
    }


def test_legal_and_administracion_app_roles_are_scoped_not_blanket_access() -> None:
    """Alcance confirmado por el usuario: "Administracion" ve empleados y nóminas; "Legal" ve
    documentos (contratos y similares) pero nunca el contenido de reconocimientos médicos."""
    legal = UserContext("u", "U", roles=frozenset({"Legal"}))
    assert legal.has(Permission.DOCUMENTOS_LEER)
    assert legal.has(Permission.DOCUMENTOS_CONTENIDO)
    assert not legal.has(Permission.DOCUMENTOS_CONTENIDO_MEDICO)
    assert not legal.has(Permission.NOMINAS_LEER)
    assert not legal.has(Permission.EMPLEADOS_LEER)

    administracion = UserContext("u", "U", roles=frozenset({"Administracion"}))
    assert administracion.has(Permission.NOMINAS_LEER)
    assert administracion.has(Permission.NOMINAS_IMPORTES)
    assert not administracion.has(Permission.DOCUMENTOS_CONTENIDO)


def test_rrhh_keeps_medical_document_content_access() -> None:
    """La nueva distinción "contenido médico" no debe quitarle nada a RRHH: solo restringe a
    "Legal", que nunca tuvo ese contenido."""
    assert UserContext("u", "U", roles=frozenset({"RRHH"})).has(Permission.DOCUMENTOS_CONTENIDO_MEDICO)
    assert UserContext("u", "U", roles=frozenset({"mia.rrhh"})).has(Permission.DOCUMENTOS_CONTENIDO_MEDICO)


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


async def test_entra_token_with_a_real_app_role_name_maps_to_permissions() -> None:
    """El token trae literalmente "RRHH" (el App Role tal como se definiría en el manifiesto de
    Entra ID), no el rol interno de desarrollo "mia.rrhh"."""
    token = _entra_token(roles=["RRHH"])
    user = await _entra_provider().authenticate(_Request({"authorization": f"Bearer {token}"}))  # type: ignore[arg-type]
    assert user.has(Permission.NOMINAS_LEER)
    assert user.has(Permission.EMPLEADOS_LEER)


async def test_entra_accepts_v1_style_audience_and_issuer_for_api_scopes() -> None:
    """Un token real pedido con un scope de API propia (``api://<client_id>/access_as_user``)
    puede venir en formato v1 (``accessTokenAcceptedVersion`` del manifiesto en ``null``/``1``):
    iss=«sts.windows.net/<tenant>/» y aud=«api://<client_id>», no el formato v2 «de libro». Debe
    aceptarse igual que el v2 -- no depende de que alguien cambie un ajuste en Azure."""
    token = _entra_token(aud=f"api://{CLIENT_ID}", iss=f"https://sts.windows.net/{TENANT}/")
    user = await _entra_provider().authenticate(_Request({"authorization": f"Bearer {token}"}))  # type: ignore[arg-type]
    assert user.user_id == "oid-1"
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

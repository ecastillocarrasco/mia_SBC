from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from pydantic import SecretStr

from mia.connectors.sharepoint.auth import SharePointAuthError, _private_key_pem
from mia.settings import SharePointSettings


def _pfx(password: bytes) -> bytes:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "mia-test")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(datetime.now(UTC))
        .not_valid_after(datetime.now(UTC) + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    return pkcs12.serialize_key_and_certificates(
        b"mia", key, cert, None, serialization.BestAvailableEncryption(password)
    )


def test_reads_pfx_from_base64() -> None:
    settings = SharePointSettings(
        cert_pfx_base64=SecretStr(base64.b64encode(_pfx(b"secreto")).decode()),
        cert_pfx_password=SecretStr("secreto"),
    )
    assert _private_key_pem(settings).startswith("-----BEGIN PRIVATE KEY-----")


def test_wrong_password_is_a_clear_error() -> None:
    settings = SharePointSettings(
        cert_pfx_base64=SecretStr(base64.b64encode(_pfx(b"secreto")).decode()),
        cert_pfx_password=SecretStr("otra"),
    )
    with pytest.raises(SharePointAuthError, match="contraseña"):
        _private_key_pem(settings)


def test_missing_certificate() -> None:
    with pytest.raises(SharePointAuthError, match="Falta el certificado"):
        _private_key_pem(SharePointSettings())

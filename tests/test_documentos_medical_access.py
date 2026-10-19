"""Acceso al CONTENIDO de "Reconocimiento médico": exige ``Permission.DOCUMENTOS_CONTENIDO_MEDICO``
además de ``DOCUMENTOS_CONTENIDO`` (ver ``mia.auth.context`` y ``mia.modules.rrhh.documentos.
tools.is_medical_document_type``). Decisión de negocio: el rol "Legal" ve documentos (contratos y
similares) pero nunca el contenido de reconocimientos médicos; RRHH conserva el acceso completo.
"""

from __future__ import annotations

import io
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from reportlab.pdfgen import canvas

from mia.api.services import Services
from mia.auth import UserContext
from mia.auth.providers import DevIdentityProvider
from mia.connectors.sharepoint import SharePointClient, StaticTokenProvider
from mia.conversation import ToolContext, ToolRegistry, ToolStatus
from mia.data import Database, Employee, SignedDocument
from mia.llm import ToolCall
from mia.llm.fake import FakeLLMProvider
from mia.modules.rrhh import build_registry
from mia.settings import AuthSettings, Environment, Settings
from mia.text import normalize_key
from tests.dbutil import fresh_database

CONTRATO_ID = 501
MEDICO_ID = 502
EMPLEADO_ID = 9
LEGAL = UserContext("legal-1", "Legal", roles=frozenset({"Legal"}))
RRHH = UserContext("rrhh-1", "RRHH", roles=frozenset({"RRHH"}))


def _pdf(text: str) -> bytes:
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.drawString(40, 800, text)
    pdf.save()
    return buffer.getvalue()


def _mock_sharepoint() -> SharePointClient:
    content = _pdf("Contenido de prueba")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content)

    return SharePointClient(
        site_url="https://contoso.sharepoint.com/sites/rrhh",
        tokens=StaticTokenProvider(),
        transport=httpx.MockTransport(handler),
    )


async def _seed_documents(db: Database) -> None:
    async with db.session() as s:
        s.add_all(
            [
                Employee(
                    sp_id=EMPLEADO_ID,
                    name="Empleado X",
                    name_key=normalize_key("Empleado X"),
                    active=True,
                    department="Pisos",
                    department_key=normalize_key("Pisos"),
                    email="x@sbc.test",
                    person_key="pk-x",
                ),
                SignedDocument(sp_id=CONTRATO_ID, person_key="pk-x", doc_type="Contrato", file_name="contrato.pdf"),
                SignedDocument(
                    sp_id=MEDICO_ID, person_key="pk-x", doc_type="Reconocimiento médico", file_name="medico.pdf"
                ),
            ]
        )


NOW = datetime(2026, 9, 15, 10, 0, tzinfo=ZoneInfo("Europe/Madrid"))


async def _call(
    registry: ToolRegistry, name: str, user: UserContext, **args: Any
) -> Any:
    ctx = ToolContext(user=user, request_id="r1", now=NOW, session_state={})
    execution = await registry.execute(ToolCall("c", name, json.dumps(args)), ctx)
    return execution.result


@pytest.fixture
async def registry_env(tmp_path: Path):
    db = await fresh_database(tmp_path, "docmed.db")
    await _seed_documents(db)
    settings = Settings(_env_file=None, environment=Environment.TEST)
    sharepoint = _mock_sharepoint()
    registry = build_registry(db, settings=settings, llm=FakeLLMProvider(), sharepoint=sharepoint)
    yield registry
    await sharepoint.aclose()
    await db.dispose()


async def test_legal_cannot_read_medical_document_content(registry_env: ToolRegistry) -> None:
    result = await _call(registry_env, "leer_documento", LEGAL, empleado_id=EMPLEADO_ID, tipo="reconocimiento medico")
    assert result.status is ToolStatus.PERMISSION_DENIED


async def test_legal_can_still_read_a_contract(registry_env: ToolRegistry) -> None:
    result = await _call(registry_env, "leer_documento", LEGAL, empleado_id=EMPLEADO_ID, tipo="contrato")
    assert result.status is ToolStatus.OK


async def test_rrhh_can_read_medical_document_content(registry_env: ToolRegistry) -> None:
    result = await _call(registry_env, "leer_documento", RRHH, empleado_id=EMPLEADO_ID, tipo="reconocimiento medico")
    assert result.status is ToolStatus.OK


async def test_legal_document_viewer_omits_medical_entry_but_keeps_the_contract(
    registry_env: ToolRegistry,
) -> None:
    """Legal tiene DOCUMENTOS_CONTENIDO (ve el visor de documentos), pero no DOCUMENTOS_CONTENIDO_MEDICO:
    el contrato debe seguir apareciendo en el visor, el reconocimiento médico no."""
    result = await _call(registry_env, "documentos_persona", LEGAL, empleado_id=EMPLEADO_ID)
    assert result.status is ToolStatus.OK
    urls = {d["url"] for d in result.presentation["documents"]}
    assert f"/api/documents/documento/{CONTRATO_ID}" in urls
    assert f"/api/documents/documento/{MEDICO_ID}" not in urls


async def test_rrhh_document_viewer_includes_the_medical_entry(registry_env: ToolRegistry) -> None:
    result = await _call(registry_env, "documentos_persona", RRHH, empleado_id=EMPLEADO_ID)
    assert result.status is ToolStatus.OK
    urls = {d["url"] for d in result.presentation["documents"]}
    assert f"/api/documents/documento/{CONTRATO_ID}" in urls
    assert f"/api/documents/documento/{MEDICO_ID}" in urls


# ------------------------------------------------------------------ descarga directa /api/documents
async def test_legal_download_of_medical_document_is_forbidden(
    client: httpx.AsyncClient, services: Services
) -> None:
    await _seed_documents(services.db)
    services.sharepoint = _mock_sharepoint()
    services.identity = DevIdentityProvider(AuthSettings(dev_user_id="legal-1", dev_roles=["Legal"]))
    response = await client.get(f"/api/documents/documento/{MEDICO_ID}")
    assert response.status_code == 403


async def test_legal_download_of_a_contract_still_works(client: httpx.AsyncClient, services: Services) -> None:
    await _seed_documents(services.db)
    services.sharepoint = _mock_sharepoint()
    services.identity = DevIdentityProvider(AuthSettings(dev_user_id="legal-1", dev_roles=["Legal"]))
    response = await client.get(f"/api/documents/documento/{CONTRATO_ID}")
    assert response.status_code == 200


async def test_rrhh_download_of_medical_document_still_works(client: httpx.AsyncClient, services: Services) -> None:
    await _seed_documents(services.db)
    services.sharepoint = _mock_sharepoint()
    services.identity = DevIdentityProvider(AuthSettings(dev_user_id="rrhh-1", dev_roles=["RRHH"]))
    response = await client.get(f"/api/documents/documento/{MEDICO_ID}")
    assert response.status_code == 200

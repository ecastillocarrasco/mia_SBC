"""Fase 4: transformaciones, seudonimización de rutas e indexación de CVs."""

from __future__ import annotations

import io
from collections.abc import AsyncIterator
from pathlib import Path
from zoneinfo import ZoneInfo

import docx
import pytest
from sqlalchemy import func, select

from mia.data import CvChunk, CvText, Database, Payslip, SignedDocument, SourceItem
from mia.domains.curriculums.indexer import CvIndexer, chunk_text, extract_text
from mia.llm.fake import FakeLLMProvider
from mia.sources import Pseudonymizer, definitions
from mia.sources.mappers import docs
from mia.sources.mappers.common import MapContext
from mia.sources.sharepoint import SharePointClient, StaticTokenProvider
from mia.sync import SyncRunner
from tests.dbutil import fresh_database
from tests.fakes.sharepoint import FakeSharePoint

CTX = MapContext(tz=ZoneInfo("Europe/Madrid"), pseudonymize=Pseudonymizer("k"))


@pytest.mark.parametrize(
    ("name", "label", "expected"),
    [
        ("2026-08_Agosto.pdf", None, (2026, 8, False)),
        ("2025-9_Septiembre.pdf", None, (2025, 9, False)),
        ("2025-12_Diciembre.pdf", None, (2025, 12, False)),
        ("2025-71_Extra Julio.pdf", None, (2025, 7, True)),
        ("2026-08_Agosto.pdf", "Julio", (2026, 7, False)),  # MesNomina manda
        ("sin_fecha.pdf", None, (None, None, False)),
    ],
)
def test_payslip_period(name: str, label: str | None, expected: tuple[object, ...]) -> None:
    """NOM-001: 10-12 no se confunden con 1; los códigos no mensuales son pagas especiales."""
    assert docs.payslip_period(name, label) == expected


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("Contrato_2024.pdf", "Contrato"),
        ("Prorroga contrato.pdf", "Prórroga contractual"),
        ("RM_2025.pdf", "Reconocimiento médico"),
        ("Politica seguridad de la informacion.pdf", "Normativa"),
        ("Curso PRL.pdf", "Prevención"),
        ("Certificado curso excel.pdf", "Formación"),
        ("Informacion general.pdf", "Otros"),  # «informacion» no es «formación»
    ],
)
def test_document_type(name: str, kind: str) -> None:
    assert docs.document_type(name) == kind


def test_cv_file_name_is_the_candidate_id() -> None:
    row = docs.cv_document({"ID": 5, "FileLeafRef": "8316.pdf", "FileRef": "/CVDocs/8316.pdf"}, CTX)[0]
    assert row["candidate_id"] == 8316
    assert docs.cv_document({"ID": 6, "FileSystemObjectType": 1, "FileRef": "/CVDocs/x"}, CTX) == []


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[Database]:
    database = await fresh_database(tmp_path, "p4.db")
    yield database
    await database.dispose()


async def test_identity_folders_never_store_the_id(db: Database) -> None:
    fake = FakeSharePoint(page_size=10)
    fake.put("Nominas", {"ID": 1, "FileSystemObjectType": 1, "FileRef": "/RRHH/Nominas/12345678Z"})
    fake.put(
        "Nominas",
        {
            "ID": 2,
            "FileLeafRef": "2026-08_Agosto.pdf",
            "FileRef": "/RRHH/Nominas/12345678Z/2026-08_Agosto.pdf",
            "FileDirRef": "/RRHH/Nominas/12345678Z",
            "Leido": False,
            "UsuarioNomina": {"Title": "Ana", "EMail": "ana@sbc.test"},
        },
    )
    fake.put(
        "DocumentosFirmadosV2",
        {
            "ID": 3,
            "FileLeafRef": "Contrato_12345678Z_2024.pdf",
            "FileRef": "/RRHH/Docs/12345678Z/Contrato_12345678Z_2024.pdf",
        },
    )
    client = SharePointClient(
        site_url="https://x/sites/rrhh", tokens=StaticTokenProvider(), transport=fake.transport()
    )
    pseudo = Pseudonymizer("clave")
    runner = SyncRunner(db=db, client=client, pseudonymize=pseudo)
    await runner.run(definitions.NOMINAS)
    await runner.run(definitions.DOCUMENTOS_FIRMADOS)
    await client.aclose()
    async with db.session() as s:
        raw = " ".join(str(r.payload) for r in (await s.scalars(select(SourceItem))).all())
        slip = (await s.scalars(select(Payslip))).one()
        doc = (await s.scalars(select(SignedDocument))).one()
    assert "12345678Z" not in raw
    assert slip.person_key == pseudo("12345678Z") == doc.person_key
    assert (slip.period, slip.read, slip.employee_email) == ("2026-08", False, "ana@sbc.test")
    assert doc.doc_type == "Contrato" and "12345678Z" not in (doc.file_name or "")


def _docx(text: str) -> bytes:
    document = docx.Document()
    for paragraph in text.split("\n"):
        document.add_paragraph(paragraph)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_text_extraction_and_chunks() -> None:
    status, text = extract_text(
        _docx("Camarera de pisos con cinco años de experiencia.\nInglés alto."), "1.docx"
    )
    assert status == "ok" and "Inglés alto" in text
    assert extract_text(b"\x89PNG....", "foto.png")[0] == "unsupported"
    chunks = chunk_text("palabra " * 600)
    assert len(chunks) > 1 and all(len(c) <= 1200 for c in chunks)


async def test_cv_indexer_processes_only_new_or_changed(db: Database) -> None:
    fake = FakeSharePoint(page_size=10)
    fake.put(
        "CVDocs",
        {
            "ID": 1,
            "FileLeafRef": "8316.docx",
            "FileRef": "/CVDocs/8316.docx",
            "Modified": "2026-09-01T10:00:00Z",
        },
    )
    fake.files["/CVDocs/8316.docx"] = _docx(
        "Recepcionista con experiencia en hoteles de cinco estrellas y alemán fluido."
    )
    client = SharePointClient(
        site_url="https://x/sites/rrhh", tokens=StaticTokenProvider(), transport=fake.transport()
    )
    await SyncRunner(db=db, client=client, pseudonymize=Pseudonymizer("k")).run(definitions.CV_DOCS)
    indexer = CvIndexer(db=db, client=client, llm=FakeLLMProvider(), embedding_model="x")
    first = await indexer.run()
    second = await indexer.run()
    await client.aclose()
    assert (first.indexed, second.processed) == (1, 0)
    async with db.session() as s:
        text = (await s.scalars(select(CvText))).one()
        chunks = await s.scalar(select(func.count()).select_from(CvChunk))
    assert text.status == "ok" and text.candidate_id == 8316 and chunks == 1

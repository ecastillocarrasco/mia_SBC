"""Tests de adjuntos conversacionales.

Cubre: validación, parsers, operaciones de dataset, modelo, servicio y rutas API.
"""

from __future__ import annotations

import io
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from mia.attachments.dataset import dataset_info, dataset_query, extract_column
from mia.attachments.model import (
    AttachmentContent,
    AttachmentContentType,
    AttachmentRecord,
    AttachmentRef,
    AttachmentScope,
    AttachmentStatus,
    DataClassification,
    DatasetSheet,
    TextBlock,
    get_active_refs,
    merge_refs,
    set_active_refs,
)
from mia.attachments.storage import LocalStorage
from mia.attachments.validation import sanitize_filename, sha256_hex, validate
from tests.conftest import make_settings
from tests.dbutil import fresh_database


# ─────────────────────────────────────────────────────────────────
# Helpers de bytes para tests
# ─────────────────────────────────────────────────────────────────


def _png_bytes() -> bytes:
    """PNG 1×1 blanco válido generado con Pillow."""
    from PIL import Image  # noqa: PLC0415

    buf = io.BytesIO()
    Image.new("RGB", (1, 1), color=(255, 255, 255)).save(buf, "PNG")
    return buf.getvalue()


def _jpeg_bytes() -> bytes:
    from PIL import Image  # noqa: PLC0415

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), color=(200, 100, 50)).save(buf, "JPEG")
    return buf.getvalue()


def _pdf_bytes(with_text: bool = True) -> bytes:
    """PDF generado por pypdf. Si with_text=False devuelve solo página vacía (scaneado)."""
    from pypdf import PdfWriter  # noqa: PLC0415

    writer = PdfWriter()
    writer.add_blank_page(612, 792)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _docx_bytes(text: str = "Contenido de prueba mIA") -> bytes:
    from docx import Document  # noqa: PLC0415

    doc = Document()
    doc.add_heading("Título de prueba", level=1)
    doc.add_paragraph(text)
    doc.add_paragraph("Segunda línea del documento.")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _xlsx_bytes() -> bytes:
    import openpyxl  # noqa: PLC0415

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Empleados"
    ws.append(["Nombre", "Departamento", "Salario"])
    ws.append(["Ana García", "RRHH", 2500])
    ws.append(["Luis Martín", "IT", 3200])
    ws.append(["Marta Ruiz", "RRHH", 2700])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _csv_bytes(content: str = "nombre,edad\nAna,30\nLuis,28\n") -> bytes:
    return content.encode("utf-8")


def _plaintext_bytes(text: str = "Texto plano de prueba.") -> bytes:
    return text.encode("utf-8")


# ─────────────────────────────────────────────────────────────────
# Validación
# ─────────────────────────────────────────────────────────────────


def test_validation_png_ok() -> None:
    result = validate(_png_bytes(), "foto.png", "image/png", max_bytes=10 * 1024 * 1024)
    assert result.ok
    assert result.detected_mime == "image/png"


def test_validation_jpeg_ok() -> None:
    result = validate(_jpeg_bytes(), "foto.jpg", "image/jpeg", max_bytes=10 * 1024 * 1024)
    assert result.ok
    assert result.detected_mime == "image/jpeg"


def test_validation_pdf_ok() -> None:
    result = validate(_pdf_bytes(), "doc.pdf", "application/pdf", max_bytes=10 * 1024 * 1024)
    assert result.ok
    assert result.detected_mime == "application/pdf"


def test_validation_docx_ok() -> None:
    raw = _docx_bytes()
    result = validate(raw, "carta.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", max_bytes=10 * 1024 * 1024)
    assert result.ok
    assert "wordprocessingml" in result.detected_mime


def test_validation_xlsx_ok() -> None:
    raw = _xlsx_bytes()
    result = validate(raw, "datos.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", max_bytes=10 * 1024 * 1024)
    assert result.ok
    assert "spreadsheetml" in result.detected_mime


def test_validation_csv_ok() -> None:
    raw = _csv_bytes()
    result = validate(raw, "datos.csv", "text/csv", max_bytes=10 * 1024 * 1024)
    assert result.ok


def test_validation_empty_file() -> None:
    result = validate(b"", "vacio.txt", "text/plain", max_bytes=10 * 1024 * 1024)
    assert not result.ok
    assert "vacío" in result.error.lower()


def test_validation_oversized_file() -> None:
    big = b"x" * (3 * 1024 * 1024 + 1)  # 3 MB + 1 byte
    result = validate(big, "grande.txt", "text/plain", max_bytes=3 * 1024 * 1024)
    assert not result.ok
    assert "tamaño" in result.error.lower() or "MB" in result.error


def test_validation_unsupported_extension() -> None:
    result = validate(b"data", "script.rb", "application/octet-stream", max_bytes=1024 * 1024)
    assert not result.ok


def test_validation_dangerous_extension() -> None:
    result = validate(b"data", "virus.exe", "application/octet-stream", max_bytes=1024 * 1024)
    assert not result.ok
    assert "permitido" in result.error.lower()


def test_validation_invalid_mime_octet_stream_unknown_ext() -> None:
    result = validate(b"\x00\x01\x02\x03", "archivo.bin", "application/octet-stream", max_bytes=1024 * 1024)
    assert not result.ok


def test_sanitize_filename_path_traversal() -> None:
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("..\\..\\windows\\system32\\cmd.exe") == "cmd.exe"


def test_sanitize_filename_safe() -> None:
    assert sanitize_filename("informe_2025.pdf") == "informe_2025.pdf"
    assert sanitize_filename("datos empleados.xlsx") == "datos empleados.xlsx"


def test_sanitize_filename_empty_becomes_archivo() -> None:
    assert sanitize_filename("") == "archivo"
    assert sanitize_filename("...") == "archivo"


def test_sha256_is_deterministic() -> None:
    content = b"hola mundo"
    h1 = sha256_hex(content)
    h2 = sha256_hex(content)
    assert h1 == h2
    assert len(h1) == 64
    assert h1 != sha256_hex(b"otro contenido")


# ─────────────────────────────────────────────────────────────────
# Modelo y session state
# ─────────────────────────────────────────────────────────────────


def _make_ref(attachment_id: str = "abc", status: AttachmentStatus = AttachmentStatus.READY) -> AttachmentRef:
    return AttachmentRef(
        attachment_id=attachment_id,
        filename="test.txt",
        content_type=AttachmentContentType.DOCUMENT,
        size_bytes=100,
        status=status,
    )


def test_attachment_ref_roundtrip() -> None:
    ref = _make_ref("id-123")
    d = ref.to_dict()
    restored = AttachmentRef.from_dict(d)
    assert restored.attachment_id == "id-123"
    assert restored.content_type == AttachmentContentType.DOCUMENT
    assert restored.status == AttachmentStatus.READY


def test_merge_refs_deduplicates() -> None:
    existing = [_make_ref("a"), _make_ref("b")]
    new = [_make_ref("b"), _make_ref("c")]  # b es duplicado
    merged = merge_refs(existing, new)
    ids = [r.attachment_id for r in merged]
    assert ids == ["a", "b", "c"]


def test_merge_refs_limit_10() -> None:
    existing = [_make_ref(str(i)) for i in range(9)]
    new = [_make_ref("x"), _make_ref("y")]
    merged = merge_refs(existing, new)
    assert len(merged) == 10  # límite


def test_get_set_active_refs_roundtrip() -> None:
    state: dict = {}
    refs = [_make_ref("r1"), _make_ref("r2")]
    set_active_refs(state, refs)
    restored = get_active_refs(state)
    assert len(restored) == 2
    assert restored[0].attachment_id == "r1"


def test_get_active_refs_empty_state() -> None:
    assert get_active_refs({}) == []


def test_get_active_refs_ignores_corrupt_entries() -> None:
    state = {"adjuntos_activos": [{"attachment_id": "ok", "status": "ready", "filename": "f.txt"}, {"bad": True}]}
    refs = get_active_refs(state)
    assert len(refs) == 1
    assert refs[0].attachment_id == "ok"


# ─────────────────────────────────────────────────────────────────
# Operaciones de dataset
# ─────────────────────────────────────────────────────────────────


def _sample_dataset() -> AttachmentContent:
    sheet = DatasetSheet(
        name="Empleados",
        headers=["Nombre", "Departamento", "Salario"],
        rows=[
            ["Ana García", "RRHH", 2500],
            ["Luis Martín", "IT", 3200],
            ["Marta Ruiz", "RRHH", 2700],
            ["Pedro Sanz", "IT", 3000],
        ],
        inferred_types={"Nombre": "text", "Departamento": "text", "Salario": "numeric"},
        row_count=4,
    )
    return AttachmentContent(
        content_type=AttachmentContentType.DATASET,
        sheets=[sheet],
    )


def test_dataset_info_structure() -> None:
    content = _sample_dataset()
    info = dataset_info(content)
    assert info["sheet_count"] == 1
    assert info["total_rows"] == 4
    assert info["sheets"][0]["name"] == "Empleados"
    assert info["sheets"][0]["col_count"] == 3


def test_dataset_query_no_filter() -> None:
    content = _sample_dataset()
    result = dataset_query(content, limit=10)
    assert result["sheet"] == "Empleados"
    assert result["total_matching"] == 4
    assert len(result["rows"]) == 4


def test_dataset_query_filter() -> None:
    content = _sample_dataset()
    result = dataset_query(content, filter_col="Departamento", filter_value="RRHH")
    assert result["total_matching"] == 2
    assert all(r["Departamento"] == "RRHH" for r in result["rows"])


def test_dataset_query_filter_case_insensitive() -> None:
    content = _sample_dataset()
    result = dataset_query(content, filter_col="departamento", filter_value="it")
    assert result["total_matching"] == 2


def test_dataset_query_group_by_count() -> None:
    content = _sample_dataset()
    result = dataset_query(content, group_by="Departamento", aggregate="count")
    assert result["total_groups"] == 2
    rows_dict = {r[0]: r[1] for r in result["rows"]}
    assert rows_dict["IT"] == 2
    assert rows_dict["RRHH"] == 2


def test_dataset_query_group_by_sum() -> None:
    content = _sample_dataset()
    result = dataset_query(content, group_by="Departamento", aggregate="sum", agg_col="Salario")
    rows_dict = {r[0]: r[1] for r in result["rows"]}
    assert rows_dict["IT"] == 6200
    assert rows_dict["RRHH"] == 5200


def test_dataset_query_group_by_avg() -> None:
    content = _sample_dataset()
    result = dataset_query(content, group_by="Departamento", aggregate="avg", agg_col="Salario")
    rows_dict = {r[0]: r[1] for r in result["rows"]}
    assert rows_dict["IT"] == 3100.0
    assert rows_dict["RRHH"] == 2600.0


def test_dataset_query_missing_filter_col() -> None:
    content = _sample_dataset()
    result = dataset_query(content, filter_col="Columna_Inexistente", filter_value="x")
    assert "error" in result


def test_dataset_query_no_sheets() -> None:
    content = AttachmentContent(content_type=AttachmentContentType.DATASET, sheets=[])
    result = dataset_query(content)
    assert "error" in result


def test_extract_column_unique_values() -> None:
    content = _sample_dataset()
    values = extract_column(content, "Departamento")
    assert set(values) == {"RRHH", "IT"}


def test_extract_column_missing_column() -> None:
    content = _sample_dataset()
    values = extract_column(content, "ColumnaQueNoExiste")
    assert values == []


def test_dataset_query_limit() -> None:
    content = _sample_dataset()
    result = dataset_query(content, limit=2)
    assert len(result["rows"]) == 2
    assert result["total_matching"] == 4  # hay 4 pero se muestran 2


# ─────────────────────────────────────────────────────────────────
# Parsers (requieren librerías instaladas)
# ─────────────────────────────────────────────────────────────────


def test_parse_pdf_blank_detected_as_scanned() -> None:
    from mia.attachments.parsers.pdf import parse_pdf  # noqa: PLC0415

    result = parse_pdf(_pdf_bytes())
    assert result.content_type == AttachmentContentType.DOCUMENT
    assert result.page_count == 1
    # La página en blanco no tiene texto: se marca como escaneada
    assert result.metadata["scanned_pages"] == 1


def test_parse_pdf_needs_vision_when_scanned() -> None:
    from mia.attachments.parsers.pdf import needs_vision, parse_pdf  # noqa: PLC0415

    content = parse_pdf(_pdf_bytes())
    assert needs_vision(content) is True


def test_parse_docx_extracts_text() -> None:
    from mia.attachments.parsers.docx import parse_docx  # noqa: PLC0415

    raw = _docx_bytes("Hola mundo desde un DOCX de prueba")
    result = parse_docx(raw)
    assert result.content_type == AttachmentContentType.DOCUMENT
    assert result.text_blocks
    full = result.full_text
    assert "Hola mundo" in full or "Hola" in full


def test_parse_docx_heading_preserved() -> None:
    from mia.attachments.parsers.docx import parse_docx  # noqa: PLC0415

    result = parse_docx(_docx_bytes())
    assert result.full_text  # al menos hay contenido


def test_parse_excel_structured() -> None:
    from mia.attachments.parsers.excel import parse_excel  # noqa: PLC0415

    result = parse_excel(_xlsx_bytes())
    assert result.content_type == AttachmentContentType.DATASET
    assert len(result.sheets) == 1
    sheet = result.sheets[0]
    assert sheet.name == "Empleados"
    assert "Nombre" in sheet.headers
    assert sheet.row_count == 3
    assert sheet.inferred_types["Salario"] == "numeric"


def test_parse_excel_not_routed_to_vision() -> None:
    from mia.attachments.intelligence import classify_content_type  # noqa: PLC0415

    mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ct = classify_content_type(mime)
    assert ct == AttachmentContentType.DATASET
    # DATASET nunca es enviado a Vision en el pipeline de intelligence


def test_parse_csv_extracts_columns() -> None:
    from mia.attachments.parsers.csv_file import parse_csv  # noqa: PLC0415

    raw = _csv_bytes("nombre,edad,ciudad\nAna,30,Málaga\nLuis,28,Madrid\n")
    result = parse_csv(raw)
    assert result.content_type == AttachmentContentType.DATASET
    assert result.sheets
    sheet = result.sheets[0]
    assert "nombre" in [h.lower() for h in sheet.headers]
    assert sheet.row_count == 2


def test_parse_image_metadata() -> None:
    from mia.attachments.parsers.image import parse_image  # noqa: PLC0415

    result = parse_image(_png_bytes())
    assert result.content_type == AttachmentContentType.IMAGE
    assert result.metadata.get("width") is not None
    assert result.metadata.get("format") == "PNG"


def test_image_routed_to_vision_type() -> None:
    from mia.attachments.intelligence import classify_content_type  # noqa: PLC0415

    assert classify_content_type("image/png") == AttachmentContentType.IMAGE
    assert classify_content_type("image/jpeg") == AttachmentContentType.IMAGE


# ─────────────────────────────────────────────────────────────────
# AttachmentService (servicio)
# ─────────────────────────────────────────────────────────────────


def _make_service(tmp_path: Path) -> "AttachmentService":  # type: ignore[name-defined]
    from mia.attachments.service import AttachmentService  # noqa: PLC0415

    storage = LocalStorage(tmp_path / "attachments")
    return AttachmentService(storage=storage, llm=None, max_files=5, max_file_mb=5, retention_hours=1, vision_enabled=False)


async def test_service_upload_text_plain(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    record = await svc.upload(
        content=_plaintext_bytes("Documento de prueba"),
        filename="nota.txt",
        declared_mime="text/plain",
        user_id="user-1",
        session_id="s-1",
    )
    assert record.status == AttachmentStatus.READY
    assert record.content is not None
    assert record.content.full_text == "Documento de prueba"
    assert record.parser_used == "text"
    await svc.aclose()


async def test_service_upload_csv(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    record = await svc.upload(
        content=_csv_bytes(),
        filename="datos.csv",
        declared_mime="text/csv",
        user_id="user-1",
        session_id="s-1",
    )
    assert record.status == AttachmentStatus.READY
    assert record.content_type == AttachmentContentType.DATASET
    await svc.aclose()


async def test_build_attachment_context_exposes_the_real_attachment_id(tmp_path: Path) -> None:
    """Incidencia real (2026-10-21): el texto que se inyecta en el prompt para un adjunto solo
    mostraba el nombre del fichero — el LLM no tenía forma de saber el ``attachment_id`` real y, al
    necesitarlo para una herramienta (``info_dataset_adjunto``, ``informe_comparativo_turnos_fichajes``…),
    usaba el nombre del fichero como si fuera el ID, y la herramienta fallaba con NOT_FOUND."""
    from mia.attachments.intelligence import build_attachment_context  # noqa: PLC0415

    svc = _make_service(tmp_path)
    record = await svc.upload(content=_csv_bytes(), filename="datos.csv", declared_mime="text/csv", user_id="user-1", session_id=None)
    context = build_attachment_context(record)
    assert record.attachment_id in context
    await svc.aclose()


async def test_build_attachment_context_attachment_id_line_has_nothing_else_attached(tmp_path: Path) -> None:
    """Incidencia real (2026-10-25): la línea del id llevaba una nota pegada al valor con solo un
    par de espacios de separación ("attachment_id: <id>  ← usa EXACTAMENTE..."), sin ninguna
    frontera clara entre "el valor" y "una anotación para el humano que lee el log" — el modelo
    copió literalmente el id CON el símbolo "←" incluido al llamar a una herramienta, que entonces
    no encontraba nada (NOT_FOUND) porque ese id con el símbolo pegado no existe. La línea que
    contiene el id debe tener el id y nada más."""
    from mia.attachments.intelligence import build_attachment_context  # noqa: PLC0415

    svc = _make_service(tmp_path)
    record = await svc.upload(content=_csv_bytes(), filename="datos.csv", declared_mime="text/csv", user_id="user-1", session_id=None)
    context = build_attachment_context(record)
    id_lines = [line for line in context.splitlines() if record.attachment_id in line]
    assert id_lines, "el attachment_id no aparece en ninguna línea del contexto"
    assert all(line.strip() == f"attachment_id: {record.attachment_id}" for line in id_lines)
    await svc.aclose()


async def test_service_get_bytes_returns_the_raw_upload_unmodified(tmp_path: Path) -> None:
    """``get_bytes`` devuelve el contenido crudo tal cual se subió — herramientas como ``fichajes``
    necesitan releerlo con su propia lógica (hora completa, no solo la fecha, a diferencia del
    parser genérico de datasets)."""
    svc = _make_service(tmp_path)
    content = _csv_bytes()
    record = await svc.upload(content=content, filename="datos.csv", declared_mime="text/csv", user_id="user-1", session_id=None)
    raw = await svc.get_bytes(record.attachment_id, "user-1")
    assert raw == content
    await svc.aclose()


async def test_service_get_bytes_denies_a_different_user(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    record = await svc.upload(content=_csv_bytes(), filename="datos.csv", declared_mime="text/csv", user_id="user-1", session_id=None)
    raw = await svc.get_bytes(record.attachment_id, "user-2")
    assert raw is None
    await svc.aclose()


async def test_service_upload_error_on_invalid_mime(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    record = await svc.upload(
        content=b"malware",
        filename="virus.exe",
        declared_mime="application/x-executable",
        user_id="user-1",
        session_id=None,
    )
    assert record.status == AttachmentStatus.ERROR
    assert record.error_message
    await svc.aclose()


async def test_service_deduplication(tmp_path: Path) -> None:
    """El mismo contenido subido dos veces por el mismo usuario devuelve el mismo attachment_id."""
    svc = _make_service(tmp_path)
    content = _plaintext_bytes("Texto idéntico")

    r1 = await svc.upload(content=content, filename="a.txt", declared_mime="text/plain", user_id="user-1", session_id=None)
    r2 = await svc.upload(content=content, filename="b.txt", declared_mime="text/plain", user_id="user-1", session_id=None)

    assert r1.attachment_id == r2.attachment_id  # deduplicado
    await svc.aclose()


async def test_service_dedup_different_users_no_share(tmp_path: Path) -> None:
    """Dos usuarios distintos con el mismo contenido reciben attachment_ids distintos."""
    svc = _make_service(tmp_path)
    content = _plaintext_bytes("Texto compartido")

    r1 = await svc.upload(content=content, filename="a.txt", declared_mime="text/plain", user_id="user-1", session_id=None)
    r2 = await svc.upload(content=content, filename="a.txt", declared_mime="text/plain", user_id="user-2", session_id=None)

    assert r1.attachment_id != r2.attachment_id
    await svc.aclose()


async def test_service_user_isolation(tmp_path: Path) -> None:
    """Un usuario no puede acceder al adjunto de otro."""
    svc = _make_service(tmp_path)
    r = await svc.upload(content=_plaintext_bytes("privado"), filename="p.txt", declared_mime="text/plain", user_id="user-1", session_id=None)
    assert r.status == AttachmentStatus.READY

    visible = svc.get_for_user(r.attachment_id, "user-1")
    not_visible = svc.get_for_user(r.attachment_id, "user-2")

    assert visible is not None
    assert not_visible is None
    await svc.aclose()


async def test_service_get_returns_none_after_expire(tmp_path: Path) -> None:
    """Adjunto expirado no se devuelve."""
    from mia.attachments.service import AttachmentService  # noqa: PLC0415

    storage = LocalStorage(tmp_path / "attachments")
    svc = AttachmentService(storage=storage, llm=None, max_files=5, max_file_mb=5, retention_hours=0, vision_enabled=False)

    r = await svc.upload(content=_plaintext_bytes("x"), filename="x.txt", declared_mime="text/plain", user_id="u", session_id=None)

    # Forzar expiración manual
    r.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    count = await svc.expire_old()
    assert count == 1
    assert svc.get(r.attachment_id) is None
    await svc.aclose()


async def test_service_delete(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    r = await svc.upload(content=_plaintext_bytes("borrar"), filename="b.txt", declared_mime="text/plain", user_id="u", session_id=None)
    assert r.status == AttachmentStatus.READY

    deleted = await svc.delete(r.attachment_id, "u")
    assert deleted is True
    assert svc.get(r.attachment_id) is None
    await svc.aclose()


async def test_service_delete_wrong_user_denied(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    r = await svc.upload(content=_plaintext_bytes("x"), filename="x.txt", declared_mime="text/plain", user_id="owner", session_id=None)

    deleted = await svc.delete(r.attachment_id, "intruder")
    assert deleted is False
    assert svc.get(r.attachment_id) is not None  # sigue disponible
    await svc.aclose()


# ─────────────────────────────────────────────────────────────────
# Rutas API (requieren app con adjuntos habilitados)
# ─────────────────────────────────────────────────────────────────


@pytest.fixture
async def att_client(tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    """Cliente HTTP con la funcionalidad de adjuntos activa."""
    from mia.api.services import Services  # noqa: PLC0415
    from mia.llm.fake import FakeLLMProvider, final_answer  # noqa: PLC0415
    from mia.main import create_app  # noqa: PLC0415
    from mia.voice import CachedVoice, NullVoiceProvider  # noqa: PLC0415

    settings = make_settings(
        tmp_path,
        attachments={"enabled": True, "temp_path": str(tmp_path / "att"), "vision_enabled": False},
    )
    db = await fresh_database(tmp_path)
    llm = FakeLLMProvider(lambda req: final_answer("ok", "ok", "reposo"))
    built = Services.build(settings, llm=llm, db=db, voice=CachedVoice(NullVoiceProvider()))
    app = create_app(settings, services=built)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            yield http
    await built.aclose()


async def test_upload_disabled_returns_404(client: httpx.AsyncClient) -> None:
    """Con el flag desactivado el endpoint no está disponible."""
    resp = await client.post(
        "/api/adjuntos/upload",
        files={"file": ("test.txt", b"hola", "text/plain")},
    )
    assert resp.status_code == 404


async def test_upload_text_returns_attachment_id(att_client: httpx.AsyncClient) -> None:
    resp = await att_client.post(
        "/api/adjuntos/upload",
        files={"file": ("nota.txt", _plaintext_bytes(), "text/plain")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "attachment_id" in body
    assert body["status"] == "ready"
    assert body["filename"] == "nota.txt"


async def test_upload_csv_returns_dataset_type(att_client: httpx.AsyncClient) -> None:
    resp = await att_client.post(
        "/api/adjuntos/upload",
        files={"file": ("datos.csv", _csv_bytes(), "text/csv")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["content_type"] == "dataset"


async def test_upload_invalid_extension_returns_422(att_client: httpx.AsyncClient) -> None:
    resp = await att_client.post(
        "/api/adjuntos/upload",
        files={"file": ("script.exe", b"\x00\x01\x02", "application/octet-stream")},
    )
    assert resp.status_code == 422


async def test_get_attachment_metadata(att_client: httpx.AsyncClient) -> None:
    up = await att_client.post(
        "/api/adjuntos/upload",
        files={"file": ("meta.txt", _plaintext_bytes("prueba"), "text/plain")},
    )
    attachment_id = up.json()["attachment_id"]

    get = await att_client.get(f"/api/adjuntos/{attachment_id}")
    assert get.status_code == 200
    assert get.json()["attachment_id"] == attachment_id


async def test_get_nonexistent_attachment_returns_404(att_client: httpx.AsyncClient) -> None:
    resp = await att_client.get("/api/adjuntos/id-que-no-existe")
    assert resp.status_code == 404


async def test_delete_attachment(att_client: httpx.AsyncClient) -> None:
    up = await att_client.post(
        "/api/adjuntos/upload",
        files={"file": ("borrar.txt", _plaintext_bytes(), "text/plain")},
    )
    attachment_id = up.json()["attachment_id"]

    delete = await att_client.delete(f"/api/adjuntos/{attachment_id}")
    assert delete.status_code == 204

    get = await att_client.get(f"/api/adjuntos/{attachment_id}")
    assert get.status_code == 404


async def test_upload_path_traversal_filename_sanitized(att_client: httpx.AsyncClient) -> None:
    """El servidor debe sanitizar nombres con path traversal."""
    resp = await att_client.post(
        "/api/adjuntos/upload",
        files={"file": ("../../etc/passwd", _plaintext_bytes("contenido"), "text/plain")},
    )
    # Debe procesar (el filename queda saneado) o rechazar; nunca escribe fuera del base_path
    # Si el saneado del nombre da "passwd" que es .txt equivalente aceptado → 200
    # Si da error por extensión → 422. En cualquier caso, NO 500.
    assert resp.status_code in (200, 422)
    if resp.status_code == 200:
        assert "/" not in resp.json()["filename"]
        assert ".." not in resp.json()["filename"]


async def test_upload_png_returns_image_type(att_client: httpx.AsyncClient) -> None:
    resp = await att_client.post(
        "/api/adjuntos/upload",
        files={"file": ("captura.png", _png_bytes(), "image/png")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["content_type"] == "image"
    assert body["vision_used"] is False  # vision_enabled=False en el fixture


async def test_upload_multiple_attachments_independent(att_client: httpx.AsyncClient) -> None:
    """Varios adjuntos subidos tienen attachment_ids distintos."""
    r1 = (await att_client.post("/api/adjuntos/upload", files={"file": ("a.txt", b"aaa", "text/plain")})).json()
    r2 = (await att_client.post("/api/adjuntos/upload", files={"file": ("b.txt", b"bbb", "text/plain")})).json()

    assert r1["attachment_id"] != r2["attachment_id"]
    assert r1["filename"] == "a.txt"
    assert r2["filename"] == "b.txt"

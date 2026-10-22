"""Incidencia real (2026-10-21): el LLM elegía ``generar_informe`` para "genera el informe
comparativo de fichajes... con los turnos..." en vez de ``informe_comparativo_turnos_fichajes`` —
``generar_informe`` no tenía tabla previa que exportar y devolvía NOT_FOUND. Mismo patrón que la
incidencia de nóminas (sección 15 de ADVANCED_REPORTING_PROGRESS.md): redirección real al tool
correcto, nunca solo una descripción mejor."""

from __future__ import annotations

import io
import json
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from openpyxl import Workbook

from mia.attachments.model import AttachmentContentType, AttachmentRef, AttachmentStatus
from mia.attachments.service import AttachmentService
from mia.attachments.storage import LocalStorage
from mia.auth import UserContext
from mia.conversation import ToolContext, ToolRegistry, ToolStatus
from mia.ingestion.mappers.hr import ShiftKind
from mia.llm import ToolCall
from mia.modules.rrhh import build_registry
from tests.dbutil import fresh_database
from tests.hr_seed import _emp, _shift

TZ = ZoneInfo("Europe/Madrid")
DAY = date(2026, 10, 12)
NOW = datetime(2026, 10, 13, 10, 0, tzinfo=TZ)
ADMIN = UserContext("u", "Enrique", roles=frozenset({"mia.admin"}))
MELANIA = "pk-melania"


def _stub_settings(reports_dir: Path) -> SimpleNamespace:
    return SimpleNamespace(reports=SimpleNamespace(directory=str(reports_dir), ttl_hours=24, logo_path=None))


def _conectia_bytes() -> bytes:
    header = (
        "Fecha", "Área", "Código del empleado", "Nombre completo", "Hora marcaje",
        "Origen del marcaje", "Motivo", "Nombre Terminal", "Tipo marcaje", "Link localización",
    )
    wb = Workbook()
    ws = wb.active
    ws.append(header)
    ws.append((datetime(2026, 10, 12, 7, 0), "1-1", "1-001080", "ROSELLO DIAZ, MELANIA", "07:00", "Normal", "", "T1", "App", ""))
    ws.append((datetime(2026, 10, 12, 15, 0), "1-1", "1-001080", "ROSELLO DIAZ, MELANIA", "15:00", "Normal", "", "T1", "App", ""))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def _attach(tmp_path: Path) -> tuple[AttachmentService, str]:
    svc = AttachmentService(storage=LocalStorage(tmp_path / "attachments"), llm=None, vision_enabled=False)
    record = await svc.upload(
        content=_conectia_bytes(), filename="MARCAJES SEMANA 41 PISOS.xlsx",
        declared_mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        user_id=ADMIN.user_id, session_id=None,
    )
    assert record.status == AttachmentStatus.READY
    assert record.content_type == AttachmentContentType.DATASET
    return svc, record.attachment_id


def _session_with_attachment(attachment_id: str) -> dict:
    ref = AttachmentRef(
        attachment_id=attachment_id, filename="MARCAJES SEMANA 41 PISOS.xlsx",
        content_type=AttachmentContentType.DATASET, size_bytes=1, status=AttachmentStatus.READY,
    )
    return {"adjuntos_activos": [ref.to_dict()]}


async def _call_generar_informe(registry: ToolRegistry, svc: AttachmentService, session_state: dict, message: str) -> object:
    ctx = ToolContext(
        user=ADMIN, request_id=None, now=NOW, session_state=session_state,
        attachment_service=svc, user_message=message,
    )
    execution = await registry.execute(ToolCall("c", "generar_informe", json.dumps({"formato": "html"})), ctx)
    return execution.result


async def test_generar_informe_redirects_to_the_real_shift_vs_clock_report(tmp_path: Path) -> None:
    db = await fresh_database(tmp_path, "redirect_1.db")
    async with db.session() as s:
        s.add(_emp(1, "Melania Rosello Diaz", "Pisos", person_key=MELANIA))
        sd = _shift(1, MELANIA, "Melania Rosello Diaz", "Pisos", DAY, ShiftKind.TRABAJO, "Pisos | 07:00-15:00")
        sd.hours = 8.0
        sd.segments = "07:00-15:00"
        s.add(sd)
    svc, attachment_id = await _attach(tmp_path)
    reg = build_registry(db, settings=_stub_settings(tmp_path / "informes"))

    result = await _call_generar_informe(
        reg, svc, _session_with_attachment(attachment_id),
        "genera el informe comparativo de fichajes de la semana 41 que te he adjuntado con los "
        "turnos de la semana 41 del departamento Pisos, resumen del departamento y detalle de cada "
        "uno de los empleados",
    )
    assert result.status is ToolStatus.OK, result.summary
    assert result.presentation["type"] == "download"
    await svc.aclose()
    await db.dispose()


async def test_redirect_picks_the_most_recent_still_valid_attachment_among_several_stale_ones(tmp_path: Path) -> None:
    """Incidencia real (2026-10-21): una conversación larga con varios reinicios del backend acumula
    en ``adjuntos_activos`` referencias a adjuntos de reinicios ANTERIORES (el almacén de adjuntos es
    en memoria, se pierde al reiniciar, pero el estado de sesión persiste) — exigir "exactamente uno"
    cancelaba la redirección en cuanto había más de una referencia, aunque las antiguas ya no
    existieran. Debe usar la más reciente que SIGA siendo válida, nunca rendirse solo por haber más
    de una referencia en la lista."""
    db = await fresh_database(tmp_path, "redirect_stale.db")
    async with db.session() as s:
        s.add(_emp(1, "Melania Rosello Diaz", "Pisos", person_key=MELANIA))
        sd = _shift(1, MELANIA, "Melania Rosello Diaz", "Pisos", DAY, ShiftKind.TRABAJO, "Pisos | 07:00-15:00")
        sd.hours = 8.0
        sd.segments = "07:00-15:00"
        s.add(sd)
    svc, attachment_id = await _attach(tmp_path)
    reg = build_registry(db, settings=_stub_settings(tmp_path / "informes"))

    stale_ref = AttachmentRef(
        attachment_id="stale-from-a-previous-restart", filename="viejo.xlsx",
        content_type=AttachmentContentType.DATASET, size_bytes=1, status=AttachmentStatus.READY,
    )
    live_ref = AttachmentRef(
        attachment_id=attachment_id, filename="MARCAJES SEMANA 41 PISOS.xlsx",
        content_type=AttachmentContentType.DATASET, size_bytes=1, status=AttachmentStatus.READY,
    )
    session_state = {"adjuntos_activos": [stale_ref.to_dict(), live_ref.to_dict()]}

    result = await _call_generar_informe(
        reg, svc, session_state,
        "genera el informe comparativo de fichajes con los turnos del departamento Pisos",
    )
    assert result.status is ToolStatus.OK, result.summary
    await svc.aclose()
    await db.dispose()


async def test_no_redirect_without_an_attached_file(tmp_path: Path) -> None:
    db = await fresh_database(tmp_path, "redirect_2.db")
    async with db.session() as s:
        s.add(_emp(1, "Melania Rosello Diaz", "Pisos", person_key=MELANIA))
    reg = build_registry(db, settings=_stub_settings(tmp_path / "informes"))
    result = await _call_generar_informe(
        reg, None, {}, "genera el informe comparativo de fichajes de la semana 41 con los turnos del departamento Pisos",
    )
    assert result.status is ToolStatus.NOT_FOUND
    assert "resultado reciente" in str(result.summary)
    await db.dispose()


async def test_no_redirect_when_the_department_is_ambiguous(tmp_path: Path) -> None:
    db = await fresh_database(tmp_path, "redirect_3.db")
    async with db.session() as s:
        s.add(_emp(1, "Melania Rosello Diaz", "Pisos", person_key=MELANIA))
        s.add(_emp(2, "Juan Perez", "Cocina", person_key="pk-juan"))
    svc, attachment_id = await _attach(tmp_path)
    reg = build_registry(db, settings=_stub_settings(tmp_path / "informes"))
    result = await _call_generar_informe(
        reg, svc, _session_with_attachment(attachment_id),
        "genera el informe comparativo de fichajes y turnos de la semana 41 de Pisos y Cocina",
    )
    assert result.status is ToolStatus.NOT_FOUND
    await svc.aclose()
    await db.dispose()


async def test_redirect_does_not_need_a_week_number_period_comes_from_the_file(tmp_path: Path) -> None:
    """Confirmado contra datos reales (2026-10-21): la "semana" que nombra el usuario no tiene por
    qué coincidir con la semana ISO real de los turnos — la redirección nunca intenta extraer un
    número de semana del texto; el periodo sale de las fechas reales del adjunto importado."""
    db = await fresh_database(tmp_path, "redirect_4.db")
    async with db.session() as s:
        s.add(_emp(1, "Melania Rosello Diaz", "Pisos", person_key=MELANIA))
        sd = _shift(1, MELANIA, "Melania Rosello Diaz", "Pisos", DAY, ShiftKind.TRABAJO, "Pisos | 07:00-15:00")
        sd.hours = 8.0
        sd.segments = "07:00-15:00"
        s.add(sd)
    svc, attachment_id = await _attach(tmp_path)
    reg = build_registry(db, settings=_stub_settings(tmp_path / "informes"))
    result = await _call_generar_informe(
        reg, svc, _session_with_attachment(attachment_id),
        "genera el informe comparativo de fichajes con los turnos del departamento Pisos",
    )
    assert result.status is ToolStatus.OK, result.summary
    await svc.aclose()
    await db.dispose()


async def test_normal_last_table_export_is_unaffected_by_the_redirect_guard(tmp_path: Path) -> None:
    """La redirección solo se dispara cuando NO hay tabla previa — una exportación normal del
    último resultado sigue funcionando exactamente igual que antes."""
    from mia.conversation.tools import LAST_TABLE  # noqa: PLC0415

    db = await fresh_database(tmp_path, "redirect_5.db")
    reg = build_registry(db, settings=_stub_settings(tmp_path / "informes"))
    presentation = {"type": "table", "title": "Plantilla", "columns": ["Departamento", "Personas"], "rows": [["Pisos", 10]]}
    ctx = ToolContext(
        user=ADMIN, request_id=None, now=NOW, session_state={LAST_TABLE: presentation},
        user_message="genera el informe comparativo de fichajes con los turnos de la semana 41 de Pisos",
    )
    execution = await reg.execute(ToolCall("c", "generar_informe", json.dumps({"formato": "html"})), ctx)
    assert execution.result.status is ToolStatus.OK, execution.result.summary
    await db.dispose()

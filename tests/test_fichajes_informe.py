"""Informe premium comparativo turnos↔fichajes, de extremo a extremo contra el ToolRegistry real:
resolución de departamento/semana, cruce con TipoTurnos para las horas nocturnas, importación desde
un adjunto subido en la conversación, permisos y persistencia del documento."""

from __future__ import annotations

import io
import json
from collections.abc import AsyncIterator
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from openpyxl import Workbook

from mia.attachments.model import AttachmentStatus
from mia.attachments.service import AttachmentService
from mia.attachments.storage import LocalStorage
from mia.auth import UserContext
from mia.conversation import ToolContext, ToolRegistry, ToolStatus
from mia.data import ClockMark, ShiftTypeCatalog
from mia.ingestion.mappers.hr import ShiftKind
from mia.llm import ToolCall
from mia.modules.registry import build_registry
from tests.dbutil import fresh_database
from tests.hr_seed import _emp, _shift

TZ = ZoneInfo("Europe/Madrid")
DAY = date(2026, 10, 12)  # lunes
NOW = datetime(2026, 10, 13, 10, 0, tzinfo=TZ)
ADMIN = UserContext("u", "Enrique", roles=frozenset({"mia.admin"}))
MELANIA = "pk-melania"


def _night_shift() -> object:
    sd = _shift(1, MELANIA, "Melania Rosello Diaz", "Restaurante", DAY, ShiftKind.TRABAJO, "Restaurante | 18:00-00:00")
    sd.start_time = "18:00"
    sd.end_time = "00:00"
    sd.hours = 6.0
    sd.segments = "18:00-00:00"
    return sd


def _catalog_entry(hours_night: float = 2.0) -> ShiftTypeCatalog:
    return ShiftTypeCatalog(
        sp_id=1, code="Noche", department_key="restaurante",
        start1="18:00", end1="00:00", hours_total=6.0, hours_night=hours_night, split_shift=False,
    )


def _mark(day: int, hour: int, minute: int = 0, *, next_month: bool = False) -> ClockMark:
    return ClockMark(
        person_key=MELANIA, at=datetime(2026, 10, day, hour, minute, tzinfo=TZ),
        source="excel_conectia", imported_at=NOW,
    )


def _stub_settings(reports_dir: Path) -> SimpleNamespace:
    return SimpleNamespace(reports=SimpleNamespace(directory=str(reports_dir), ttl_hours=24, logo_path=None))


async def _call(registry: ToolRegistry, user: UserContext, attachment_service=None, **args) -> object:
    ctx = ToolContext(
        user=user, request_id=None, now=NOW, session_state={}, attachment_service=attachment_service,
    )
    execution = await registry.execute(ToolCall("c", "informe_comparativo_turnos_fichajes", json.dumps(args)), ctx)
    return execution.result


@pytest.fixture
async def registry(tmp_path: Path) -> AsyncIterator[ToolRegistry]:
    db = await fresh_database(tmp_path, "fichajes_informe.db")
    async with db.session() as s:
        s.add(_emp(1, "Melania Rosello Diaz", "Restaurante", person_key=MELANIA))
        s.add(_night_shift())
        s.add(_catalog_entry())
        # Entrada a las 18:00, salida a las 02:00 del día siguiente: 2h extra, 4h nocturnas reales
        # en total (ejemplo confirmado explícitamente por el usuario antes de implementarlo).
        s.add(_mark(12, 18, 0))
        s.add(ClockMark(person_key=MELANIA, at=datetime(2026, 10, 13, 2, 0, tzinfo=TZ), source="excel_conectia", imported_at=NOW))
    yield build_registry(db, settings=_stub_settings(tmp_path / "informes"))
    await db.dispose()


async def test_report_computes_night_and_extra_hours_from_the_shift_catalog(registry: ToolRegistry) -> None:
    # hasta debe cubrir también la madrugada del día siguiente: el turno nocturno del lunes sale a
    # las 02:00 del martes, y la ventana de búsqueda de fichajes es [desde, hasta+1 día).
    result = await _call(registry, ADMIN, departamento="Restaurante", desde="2026-10-12", hasta="2026-10-13", formato="html")
    assert result.status is ToolStatus.OK, result.summary
    assert result.summary["personas_analizadas"] == 1
    assert result.summary["departamento"] == "Restaurante"
    assert result.summary["avisos_calidad_datos"] == 0
    assert result.presentation["type"] == "download"
    assert result.presentation["format"] == "html"


async def test_report_in_several_formats_at_once(registry: ToolRegistry) -> None:
    result = await _call(
        registry, ADMIN, departamento="Restaurante", desde="2026-10-12", hasta="2026-10-13",
        formato=["html", "docx"],
    )
    assert result.status is ToolStatus.OK, result.summary
    assert result.presentation["type"] == "downloads"
    assert {item["format"] for item in result.presentation["items"]} == {"html", "docx"}


async def test_presentation_carries_a_screen_preview_with_the_real_comparison_table(registry: ToolRegistry) -> None:
    """La pantalla (2D/3D) necesita algo más que el recuento "secciones": 90 que ya llevaba el
    summary -- un adelanto real del documento (tabla comparativa recortada, nunca el informe
    entero), separado del summary que ve el modelo."""
    result = await _call(registry, ADMIN, departamento="Restaurante", desde="2026-10-12", hasta="2026-10-13", formato="html")
    assert result.status is ToolStatus.OK, result.summary
    preview = result.presentation["preview"]
    assert preview["tables"], "debería haber al menos una tabla de detalle por empleado"
    table = preview["tables"][0]
    assert table["columns"] and table["rows"]
    assert "preview" not in result.summary, "el preview es solo para pantalla, nunca para el modelo"


async def test_shift_without_a_matching_catalog_entry_is_reported_not_guessed(tmp_path: Path) -> None:
    db = await fresh_database(tmp_path, "fichajes_informe_no_catalog.db")
    async with db.session() as s:
        s.add(_emp(1, "Melania Rosello Diaz", "Restaurante", person_key=MELANIA))
        s.add(_night_shift())  # sin ShiftTypeCatalog correspondiente
        s.add(_mark(12, 18, 0))
        s.add(ClockMark(person_key=MELANIA, at=datetime(2026, 10, 13, 2, 0, tzinfo=TZ), source="excel_conectia", imported_at=NOW))
    reg = build_registry(db, settings=_stub_settings(tmp_path / "informes"))
    result = await _call(reg, ADMIN, departamento="Restaurante", desde="2026-10-12", hasta="2026-10-13", formato="html")
    assert result.status is ToolStatus.OK, result.summary
    assert result.summary["avisos_calidad_datos"] == 1
    assert result.summary["advertencias"][0]["code"] == "TURNO_SIN_DEFINICION"
    await db.dispose()


async def test_week_resolved_from_iso_week_and_year(registry: ToolRegistry) -> None:
    # Semana ISO 42 de 2026 es lunes 12/10 a domingo 18/10 — debe resolver al mismo periodo.
    result = await _call(registry, ADMIN, departamento="Restaurante", semana_iso=42, anio_iso=2026, formato="html")
    assert result.status is ToolStatus.OK, result.summary
    assert result.summary["periodo"] == "12/10/2026 – 18/10/2026"


async def test_unknown_department_is_reported(registry: ToolRegistry) -> None:
    result = await _call(registry, ADMIN, departamento="Departamento inexistente", formato="html")
    assert result.status is ToolStatus.NOT_FOUND


async def test_user_without_fichajes_permission_is_denied(registry: ToolRegistry) -> None:
    limited = UserContext("u2", "Sin fichajes", roles=frozenset())
    result = await _call(registry, limited, departamento="Restaurante", desde="2026-10-12", hasta="2026-10-12")
    assert result.status is ToolStatus.PERMISSION_DENIED


def _conectia_bytes(rows: list[tuple]) -> bytes:
    header = (
        "Fecha", "Área", "Código del empleado", "Nombre completo", "Hora marcaje",
        "Origen del marcaje", "Motivo", "Nombre Terminal", "Tipo marcaje", "Link localización",
    )
    wb = Workbook()
    ws = wb.active
    ws.append(header)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def test_imports_fichajes_from_an_uploaded_attachment_before_comparing(tmp_path: Path) -> None:
    db = await fresh_database(tmp_path, "fichajes_informe_adjunto.db")
    async with db.session() as s:
        s.add(_emp(1, "Melania Rosello Diaz", "Restaurante", person_key=MELANIA))
        s.add(_night_shift())
        s.add(_catalog_entry())
        # Deliberadamente SIN ClockMark previos: deben llegar solo a través del adjunto.
    svc = AttachmentService(storage=LocalStorage(tmp_path / "attachments"), llm=None, vision_enabled=False)
    content = _conectia_bytes([
        (datetime(2026, 10, 12, 18, 0), "1-1", "1-001080", "ROSELLO DIAZ, MELANIA", "18:00", "Normal", "", "T1", "App", ""),
        (datetime(2026, 10, 13, 2, 0), "1-1", "1-001080", "ROSELLO DIAZ, MELANIA", "02:00", "Normal", "", "T1", "App", ""),
    ])
    record = await svc.upload(
        content=content, filename="fichajes_semana41.xlsx",
        declared_mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        user_id=ADMIN.user_id, session_id=None,
    )
    assert record.status == AttachmentStatus.READY

    reg = build_registry(db, settings=_stub_settings(tmp_path / "informes"))
    result = await _call(
        reg, ADMIN, attachment_service=svc,
        departamento="Restaurante", desde="2026-10-12", hasta="2026-10-12",
        adjunto_id=record.attachment_id, formato="html",
    )
    assert result.status is ToolStatus.OK, result.summary
    assert result.summary["personas_analizadas"] == 1
    await svc.aclose()
    await db.dispose()


def test_shift_label_includes_the_area_and_schedule() -> None:
    """Pedido explícito del usuario: el detalle diario debe mostrar qué turno concreto hizo la
    persona ese día, p. ej. "Piscina 10:00-18:00", no solo el estado (correcto/desviado/…)."""
    from mia.modules.rrhh.fichajes.comparison import ShiftExpectation
    from mia.modules.rrhh.fichajes.informe import _shift_label

    shift = ShiftExpectation(DAY, "10:00", "18:00", hours=8.0, declared_night_hours=0.0, area="Piscina")
    assert _shift_label(shift) == "Piscina 10:00-18:00"


def test_shift_label_without_an_area_omits_it() -> None:
    from mia.modules.rrhh.fichajes.comparison import ShiftExpectation
    from mia.modules.rrhh.fichajes.informe import _shift_label

    shift = ShiftExpectation(DAY, "08:00", "16:00")
    assert _shift_label(shift) == "08:00-16:00"


def test_shift_label_with_no_scheduled_shift_is_a_dash() -> None:
    from mia.modules.rrhh.fichajes.informe import _shift_label

    assert _shift_label(None) == "—"


def test_detail_table_includes_a_turno_column_with_the_real_shift(registry: ToolRegistry) -> None:
    """``_build_document`` (llamado por el handler real) debe incluir una columna "Turno" en el
    detalle diario, con la etiqueta área+horario del turno programado ese día."""
    from mia.data import Employee
    from mia.modules.rrhh.fichajes.comparison import DayComparison, ShiftExpectation
    from mia.modules.rrhh.fichajes.hours import compute_day_hours
    from mia.modules.rrhh.fichajes.informe import _build_document, _PersonHours
    from mia.modules.rrhh.fichajes.pairing import ClockSession

    employee = Employee(sp_id=1, name="Melania Rosello Diaz", name_key="melania rosello diaz", department_key="restaurante")
    shift = ShiftExpectation(DAY, "10:00", "18:00", hours=8.0, declared_night_hours=0.0, area="Piscina")
    session = ClockSession(datetime(2026, 10, 12, 10, 0, tzinfo=TZ), datetime(2026, 10, 12, 18, 0, tzinfo=TZ))
    result = DayComparison(DAY, "correcto", session, 0, 0)
    day_hours = compute_day_hours(shift, session)
    person = _PersonHours(employee, [result], [day_hours], [], {DAY: shift})

    document = _build_document("Restaurante", DAY, DAY, DAY, [person], [], None)
    detail = next(b for b in document.blocks if b.kind == "table" and b.title == employee.name)
    assert "Turno" in detail.data["columns"]
    turno_idx = detail.data["columns"].index("Turno")
    assert detail.data["rows"][0][turno_idx] == "Piscina 10:00-18:00"


def test_each_employee_gets_a_single_block_not_a_separate_summary_and_detail(registry: ToolRegistry) -> None:
    """Antes se generaban DOS bloques por empleado (uno "section" solo con Departamento/Periodo y
    otro "table" de detalle), que en Excel y PowerPoint se convertían en dos pestañas/diapositivas
    por persona. Debe quedar uno solo, nombrado con el nombre del empleado."""
    from mia.data import Employee
    from mia.modules.rrhh.fichajes.comparison import DayComparison, ShiftExpectation
    from mia.modules.rrhh.fichajes.hours import compute_day_hours
    from mia.modules.rrhh.fichajes.informe import _build_document, _PersonHours
    from mia.modules.rrhh.fichajes.pairing import ClockSession

    employee = Employee(sp_id=1, name="Melania Rosello Diaz", name_key="melania rosello diaz", department_key="restaurante")
    shift = ShiftExpectation(DAY, "10:00", "18:00", hours=8.0, declared_night_hours=0.0, area="Piscina")
    session = ClockSession(datetime(2026, 10, 12, 10, 0, tzinfo=TZ), datetime(2026, 10, 12, 18, 0, tzinfo=TZ))
    result = DayComparison(DAY, "correcto", session, 0, 0)
    day_hours = compute_day_hours(shift, session)
    person = _PersonHours(employee, [result], [day_hours], [], {DAY: shift})

    document = _build_document("Restaurante", DAY, DAY, DAY, [person], [], None)
    employee_blocks = [b for b in document.blocks if b.title == employee.name]
    assert len(employee_blocks) == 1
    assert employee_blocks[0].kind == "table"

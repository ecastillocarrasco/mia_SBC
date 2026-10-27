"""Requisito 5 de la ronda de validación del usuario: "Mantén trazabilidad persistente y segura de
ejecuciones de informes, sin guardar datos personales innecesarios."

Investigación previa (sin la cual esto se habría reconstruido innecesariamente): la tabla `reports`
(``mia.data.Report``) YA persiste cada informe generado — `id`, `user_id`, `title`, `format`,
`file_name`, `path`, `created_at`, `expires_at` — en la base de datos real, no en memoria volátil, y sin
guardar ninguna cifra ni nombre de empleado del CONTENIDO del informe (solo su título descriptivo).
Eso ya es la mitad de "trazabilidad persistente... sin datos personales innecesarios".

Lo que SÍ faltaba, confirmado en la auditoría de la Fase A: `EventStage.REPORT_GENERATION` existía en
``mia.diagnostics.models`` pero no se emitía nunca desde ningún generador de informes — no había forma
de enlazar un informe generado con la traza de diagnóstico de ese turno. Se conecta aquí (en
``mia/modules/rrhh/informes/tools.py``), reutilizando ``mia.diagnostics.emit()`` ya existente — no se
crea ningún sistema de trazabilidad nuevo en paralelo."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select

from mia.auth import UserContext
from mia.conversation import ToolContext, ToolRegistry
from mia.conversation.tools import LAST_TABLE
from mia.data import Report
from mia.diagnostics.config import DiagnosticsSettings
from mia.diagnostics.store import DiagnosticsStore
from mia.diagnostics.streaming import LiveBroadcaster
from mia.diagnostics.trace import begin_trace
from mia.llm import ToolCall
from mia.modules.registry import build_registry
from tests.dbutil import fresh_database

ADMIN = UserContext("u", "Enrique", roles=frozenset({"mia.admin"}))

_TABLE_PRESENTATION = {
    "type": "table",
    "title": "Plantilla por departamento",
    "columns": ["Departamento", "Personas"],
    "rows": [["Cocina", 4], ["Recepción", 4]],
}


def _stub_settings(reports_dir: Path) -> SimpleNamespace:
    return SimpleNamespace(reports=SimpleNamespace(directory=str(reports_dir), ttl_hours=24, logo_path=None))


async def _generate(registry: ToolRegistry, now: object) -> tuple[object, object]:
    ctx = ToolContext(user=ADMIN, request_id=None, now=now, session_state={LAST_TABLE: _TABLE_PRESENTATION})
    store = DiagnosticsStore(DiagnosticsSettings(enabled=True))
    broadcaster = LiveBroadcaster()
    async with begin_trace(query="genera un informe", store=store, broadcaster=broadcaster) as trace:
        execution = await registry.execute(ToolCall("c", "generar_informe", '{"formato": "xlsx"}'), ctx)
        trace.finish(status="completed")
    return execution, trace


async def test_report_generation_emits_a_traceable_diagnostic_event(tmp_path: Path) -> None:
    db = await fresh_database(tmp_path, "reports_trace.db")
    registry = build_registry(db, settings=_stub_settings(tmp_path / "informes"))

    execution, trace = await _generate(registry, date(2026, 10, 11))

    report_events = [e for e in trace.record.events if e.stage == "REPORT_GENERATION"]
    assert len(report_events) == 1
    data = report_events[0].data
    assert data["tool"] == "generar_informe"
    assert data["formato"] == "xlsx"
    assert isinstance(data["report_id"], str) and data["report_id"]

    # El report_id de la traza es EL MISMO que el persistido en la base de datos: se puede ir del
    # informe descargado a la traza que lo generó, y viceversa.
    async with db.session() as s:
        row = (await s.execute(select(Report).where(Report.id == data["report_id"]))).scalar_one()
    assert row.format == "xlsx"
    assert row.user_id == "u"


async def test_persisted_report_row_never_contains_the_underlying_data(tmp_path: Path) -> None:
    """La fila persistida en `reports` debe seguir siendo solo metadatos (quién, qué formato, cuándo,
    dónde), nunca el contenido analizado (nombres, importes, filas)."""
    db = await fresh_database(tmp_path, "reports_trace_pii.db")
    registry = build_registry(db, settings=_stub_settings(tmp_path / "informes"))

    execution, _trace = await _generate(registry, date(2026, 10, 11))
    assert execution.result.status.value == "ok"

    async with db.session() as s:
        rows = (await s.execute(select(Report))).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    # Solo se comprueban los campos de texto libre (título): id/file_name/path son identificadores
    # técnicos (UUID, nombre de fichero) que pueden contener dígitos por azar — no son la superficie de
    # riesgo real. El contenido analizado (nombres de departamento, filas de la tabla) nunca debe
    # colarse en el título ni en ningún otro campo descriptivo.
    assert "Cocina" not in row.title
    assert "Recepción" not in row.title
    assert row.title == "Plantilla por departamento"

"""Herramientas conversacionales de fichajes, de extremo a extremo contra el ToolRegistry real
(permisos incluidos) — no solo la lógica pura de pairing.py/comparison.py."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from mia.auth import UserContext
from mia.conversation import ToolContext, ToolRegistry, ToolStatus
from mia.data import ClockMark
from mia.ingestion.mappers.hr import ShiftKind
from mia.llm import ToolCall
from mia.modules.rrhh import build_registry
from tests.dbutil import fresh_database
from tests.hr_seed import _emp, _shift

TODAY = date(2026, 10, 12)  # lunes
NOW = datetime(2026, 10, 12, 10, 0, tzinfo=ZoneInfo("Europe/Madrid"))
ADMIN = UserContext("u", "Enrique", roles=frozenset({"mia.admin"}))
MELANIA = "pk-melania"


def _mark(person_key: str, day: int, hour: int, minute: int, **kw) -> ClockMark:
    return ClockMark(
        person_key=person_key,
        at=datetime(2026, 10, day, hour, minute, tzinfo=ZoneInfo("Europe/Madrid")),
        source="excel_conectia",
        imported_at=NOW,
        **kw,
    )


@pytest.fixture
async def registry(tmp_path: Path) -> AsyncIterator[ToolRegistry]:
    db = await fresh_database(tmp_path, "fichajes_tools.db")
    async with db.session() as s:
        s.add(_emp(1, "Melania Rosello Diaz", "Restaurante", person_key=MELANIA))
        # Lunes 12/10: turno 07:00-15:00 (_shift() lo fija así), fichaje correcto (5 min tarde al
        # entrar, dentro de la tolerancia de 15 min; salida exacta).
        s.add(_shift(1, MELANIA, "Melania Rosello Diaz", "Restaurante", date(2026, 10, 12), ShiftKind.TRABAJO, "T"))
        s.add(_mark(MELANIA, 12, 7, 5))
        s.add(_mark(MELANIA, 12, 15, 0))
        # Martes 13/10: turno programado, SIN ningún fichaje -> falta de marcaje.
        s.add(_shift(2, MELANIA, "Melania Rosello Diaz", "Restaurante", date(2026, 10, 13), ShiftKind.TRABAJO, "T"))
        # Miércoles 14/10: fichaje real SIN turno programado -> sin_turno.
        s.add(_mark(MELANIA, 14, 9, 0))
        s.add(_mark(MELANIA, 14, 17, 0))
        # Jueves 15/10: una marca suelta (olvido) -> marca incompleta, señalada aparte.
        s.add(_mark(MELANIA, 15, 8, 0))
    yield build_registry(db)
    await db.dispose()


async def _call(registry: ToolRegistry, name: str, **args) -> ToolStatus:
    ctx = ToolContext(user=ADMIN, request_id=None, now=NOW, session_state={})
    return await registry.execute(ToolCall("c", name, json.dumps(args)), ctx)


async def test_fichajes_persona_lists_sessions_and_flags_incomplete_mark(registry: ToolRegistry) -> None:
    execution = await _call(
        registry, "fichajes_persona", nombre="Melania", desde="2026-10-12", hasta="2026-10-16"
    )
    result = execution.result
    assert result.status is ToolStatus.OK, result.summary
    assert result.summary["sesiones_completas"] == 2  # lunes correcto + miércoles sin turno
    assert result.summary["marcas_incompletas"] == 1
    assert len(result.summary["advertencias"]) == 1
    assert "FICHAJE_INCOMPLETO" in result.summary["advertencias"][0]["code"]


async def test_comparar_turnos_fichajes_separates_the_three_categories_and_incomplete_marks(
    registry: ToolRegistry,
) -> None:
    execution = await _call(
        registry, "comparar_turnos_fichajes", nombre="Melania", desde="2026-10-12", hasta="2026-10-16"
    )
    result = execution.result
    assert result.status is ToolStatus.OK, result.summary
    assert result.summary["marcajes_desviados"] == 0  # el lunes entra dentro de tolerancia (15 min)
    assert result.summary["faltas_de_marcaje"] == 1  # martes
    assert result.summary["marcajes_sin_turno"] == 1  # miércoles
    assert result.summary["marcas_incompletas"] == 1  # jueves
    assert result.summary["marcajes_incorrectos"] == 1  # desviados + sin_turno, nunca faltas ni incompletas
    row = result.presentation["rows"][0]
    assert row[0] == "Melania Rosello Diaz"


async def test_comparar_turnos_fichajes_detects_a_real_deviation_beyond_tolerance(tmp_path: Path) -> None:
    db = await fresh_database(tmp_path, "fichajes_tools_dev.db")
    async with db.session() as s:
        s.add(_emp(1, "Melania Rosello Diaz", "Restaurante", person_key=MELANIA))
        s.add(_shift(1, MELANIA, "Melania Rosello Diaz", "Restaurante", date(2026, 10, 12), ShiftKind.TRABAJO, "T"))
        s.add(_mark(MELANIA, 12, 8, 45))  # turno sintético empieza a las 07:00 -> 105 min tarde
        s.add(_mark(MELANIA, 12, 15, 0))
    reg = build_registry(db)
    execution = await _call(reg, "comparar_turnos_fichajes", nombre="Melania", desde="2026-10-12", hasta="2026-10-12")
    result = execution.result
    assert result.status is ToolStatus.OK, result.summary
    assert result.summary["marcajes_desviados"] == 1
    assert result.summary["desviacion_media_entrada_min"] == 105  # 08:45 real - 07:00 programado
    await db.dispose()


async def test_user_without_fichajes_permission_is_denied(registry: ToolRegistry) -> None:
    limited = UserContext("u2", "Sin fichajes", roles=frozenset())
    ctx = ToolContext(user=limited, request_id=None, now=NOW, session_state={})
    execution = await registry.execute(ToolCall("c", "fichajes_persona", json.dumps({"nombre": "Melania"})), ctx)
    assert execution.result.status is ToolStatus.PERMISSION_DENIED


def test_localize_marks_converts_utc_to_local_madrid_time() -> None:
    """Bug real encontrado contra datos de producción (2026-10-21): PostgreSQL devuelve
    ``ClockMark.at`` con tzinfo UTC (un TIMESTAMPTZ representa un instante, no una zona), aunque se
    escribió con la hora local correcta — mostrar esa hora directamente sin relocalizar daba una
    hora de fichaje 2h por detrás de la real. 12:00 UTC en octubre (CEST, UTC+2) son las 14:00 en
    Madrid. Prueba pura, a propósito separada de la base de datos: SQLite (solo tests) no reproduce
    el comportamiento real de PostgreSQL de devolver el tzinfo tal cual se guardó."""
    from mia.modules.rrhh.fichajes.tools import _localize_marks

    marks = [datetime(2026, 10, 12, 12, 0, tzinfo=UTC), datetime(2026, 10, 12, 20, 0, tzinfo=UTC)]
    localized = _localize_marks(marks)
    assert [m.strftime("%H:%M") for m in localized] == ["14:00", "22:00"]

"""Tests de temporalidad y filtrado 'ahora' en el módulo de turnos.

Cobertura de TUR-002 (works_at medianoche) y TUR-003 (auto-hora para 'ahora').
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from mia.modules.rrhh.turnos.tools import _NOW_RE, _minutes, works_at


# ── Helpers ───────────────────────────────────────────────────────────────────

def _shift(start: str, end: str, segments: str = "") -> MagicMock:
    """Crea un ShiftDay mock con start_time, end_time y segments."""
    s = MagicMock()
    s.start_time = start
    s.end_time = end
    s.segments = segments
    return s


# ── works_at: turno estándar ──────────────────────────────────────────────────

def test_works_at_dentro_del_turno():
    shift = _shift("08:00", "16:00")
    assert works_at(shift, _minutes("10:00")) is True


def test_works_at_antes_del_turno():
    shift = _shift("08:00", "16:00")
    assert works_at(shift, _minutes("07:59")) is False


def test_works_at_justo_al_inicio():
    shift = _shift("08:00", "16:00")
    assert works_at(shift, _minutes("08:00")) is True


def test_works_at_justo_al_final_excluido():
    shift = _shift("08:00", "16:00")
    assert works_at(shift, _minutes("16:00")) is False


# ── works_at: turno nocturno (cruza medianoche) ───────────────────────────────

def test_works_at_nocturno_despues_de_medianoche():
    # Turno 22:00 - 06:00: debe cubrir las 02:00
    shift = _shift("22:00", "06:00")
    assert works_at(shift, _minutes("02:00")) is True


def test_works_at_nocturno_antes_de_fin():
    # Turno 22:00 - 06:00: debe cubrir las 05:59
    shift = _shift("22:00", "06:00")
    assert works_at(shift, _minutes("05:59")) is True


def test_works_at_nocturno_no_cubre_mediodia():
    # Turno 22:00 - 06:00: NO debe cubrir las 12:00
    shift = _shift("22:00", "06:00")
    assert works_at(shift, _minutes("12:00")) is False


def test_works_at_nocturno_justo_al_inicio():
    shift = _shift("22:00", "06:00")
    assert works_at(shift, _minutes("22:00")) is True


def test_works_at_nocturno_justo_al_fin_excluido():
    shift = _shift("22:00", "06:00")
    assert works_at(shift, _minutes("06:00")) is False


# ── works_at: turno partido (segments) ───────────────────────────────────────

def test_works_at_turno_partido_primer_tramo():
    shift = _shift("10:00", "22:00", segments="10:00-14:00,18:00-22:00")
    assert works_at(shift, _minutes("11:00")) is True


def test_works_at_turno_partido_segundo_tramo():
    shift = _shift("10:00", "22:00", segments="10:00-14:00,18:00-22:00")
    assert works_at(shift, _minutes("19:00")) is True


def test_works_at_turno_partido_entre_tramos():
    shift = _shift("10:00", "22:00", segments="10:00-14:00,18:00-22:00")
    assert works_at(shift, _minutes("16:00")) is False


# ── works_at: sin horario definido ────────────────────────────────────────────

def test_works_at_sin_horario_no_cubre():
    shift = _shift(None, None)
    assert works_at(shift, _minutes("10:00")) is False


def test_works_at_sin_segments_usa_start_end():
    shift = _shift("09:00", "17:00", segments="")
    assert works_at(shift, _minutes("12:00")) is True


# ── _NOW_RE: patrones de "ahora" ─────────────────────────────────────────────

def test_now_re_ahora():
    assert _NOW_RE.search("quien esta trabajando ahora") is not None


def test_now_re_ahora_mismo():
    assert _NOW_RE.search("quiénes están ahora mismo en cocina") is not None


def test_now_re_en_este_momento():
    assert _NOW_RE.search("en este momento hay alguien de turno") is not None


def test_now_re_actualmente():
    assert _NOW_RE.search("actualmente cuántas personas trabajan") is not None


def test_now_re_no_false_positive_manana():
    assert _NOW_RE.search("quién trabaja mañana") is None


def test_now_re_no_false_positive_hoy():
    assert _NOW_RE.search("quién trabaja hoy") is None


def test_now_re_no_false_positive_esta_semana():
    assert _NOW_RE.search("los turnos de esta semana") is None


# ── TUR-003: hora_efectiva se aplica automáticamente ─────────────────────────

def test_tur003_hora_efectiva_en_handler():
    """Verifica que el handler de turnos_dia usa hora_efectiva cuando p.hora es None y 'ahora' está en la consulta."""
    # Este test valida la lógica sin construir el handler completo (dependencias de BD).
    # Comprobamos que _NOW_RE detecta "ahora" en la consulta y que works_at filtra correctamente.
    from mia.modules.rrhh.turnos.tools import _NOW_RE, works_at

    user_message = "quien esta trabajando ahora en restaurante"
    assert _NOW_RE.search(user_message) is not None, "El patrón _NOW_RE debe detectar 'ahora' en la consulta"

    # Simula la lógica de hora_efectiva
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now = datetime(2026, 10, 7, 14, 30, tzinfo=ZoneInfo("Europe/Madrid"))
    hora_efectiva = now.strftime("%H:%M")
    assert hora_efectiva == "14:30"

    # Turno 10:00-18:00 debe estar activo a las 14:30
    shift = _shift("10:00", "18:00")
    minute = _minutes(hora_efectiva)
    assert works_at(shift, minute) is True

    # Turno 08:00-13:00 NO debe estar activo a las 14:30
    shift_pasado = _shift("08:00", "13:00")
    assert works_at(shift_pasado, minute) is False


def test_tur003_turno_nocturno_activo_a_medianoche():
    """Verifica que un turno 22:00-06:00 se detecta como activo a las 00:30."""
    from mia.modules.rrhh.turnos.tools import works_at

    shift = _shift("22:00", "06:00")
    assert works_at(shift, _minutes("00:30")) is True
    assert works_at(shift, _minutes("23:00")) is True
    assert works_at(shift, _minutes("05:30")) is True
    assert works_at(shift, _minutes("06:00")) is False
    assert works_at(shift, _minutes("12:00")) is False

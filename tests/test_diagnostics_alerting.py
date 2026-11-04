"""Aviso por correo cuando un turno de diagnóstico termina con un error real (MIA_DIAGNOSTICS__ALERT_EMAIL).

Cubre:
- qué cuenta como "error real" (nunca un issue de calidad de respuesta)
- que se usa el transporte SMTP dedicado, nunca Graph
- cooldown entre avisos consecutivos
- que begin_trace() agenda el aviso sin romper el flujo normal
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

import mia.diagnostics as d
from mia.diagnostics import alerting
from mia.diagnostics.alerting import _is_real_error, notify_on_error
from mia.diagnostics.models import DiagnosticIssue, TraceRecord
from mia.diagnostics.store import DiagnosticsStore
from mia.diagnostics.streaming import LiveBroadcaster
from mia.diagnostics.trace import new_trace_id
from mia.settings import DiagnosticsSettings, SmtpSettings


@pytest.fixture(autouse=True)
def _reset_cooldown():
    alerting._last_sent_at = 0.0
    yield
    alerting._last_sent_at = 0.0


def _record(**overrides: object) -> TraceRecord:
    defaults: dict[str, object] = {
        "trace_id": new_trace_id(),
        "started_at": datetime.now(UTC),
        "query": "test",
        "status": "ok",
        "tool_errors": 0,
    }
    defaults.update(overrides)
    return TraceRecord(**defaults)  # type: ignore[arg-type]


SMTP_READY = SmtpSettings(host="smtp.test", port=587, username="mia@sbc.test", from_address="mia@sbc.test")
SMTP_EMPTY = SmtpSettings()


# ── _is_real_error ───────────────────────────────────────────────────────────


def test_is_real_error_true_for_unhandled_exception():
    assert _is_real_error(_record(status="error")) is True


def test_is_real_error_false_when_a_tool_fails_but_the_turn_still_answers_ok():
    """P. ej. Graph 404 porque el usuario pidió un buzón que no existe: comportamiento correcto
    ante una entrada inválida, no una incidencia del sistema."""
    assert _is_real_error(_record(status="ok", tool_errors=1)) is False


def test_is_real_error_false_for_a_successful_turn():
    assert _is_real_error(_record(status="ok", tool_errors=0)) is False


def test_is_real_error_false_for_a_soft_quality_issue():
    """TOOL_NOT_SELECTED y similares no son un error real: solo visibles en el panel."""
    record = _record(status="ok", tool_errors=0)
    record.issues.append(DiagnosticIssue(type="TOOL_NOT_SELECTED", message="x"))
    assert _is_real_error(record) is False


# ── notify_on_error: envío real ──────────────────────────────────────────────


async def test_notify_on_error_sends_through_smtp_for_a_real_error(monkeypatch):
    sent: list[tuple[str, int]] = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=10):
            sent.append((host, port))
            self.sent_message = None

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self):
            pass

        def login(self, user, password):
            pass

        def send_message(self, message):
            self.sent_message = message
            FakeSMTP.last_message = message

    monkeypatch.setattr(alerting.smtplib, "SMTP", FakeSMTP)

    await notify_on_error(
        _record(status="error"), recipient="admin@sbc.test", smtp=SMTP_READY, cooldown_seconds=60
    )

    assert sent == [("smtp.test", 587)]
    assert FakeSMTP.last_message["To"] == "admin@sbc.test"
    assert FakeSMTP.last_message["From"] == "mia@sbc.test"


async def test_notify_on_error_does_nothing_for_a_successful_turn(monkeypatch):
    calls = []
    monkeypatch.setattr(alerting.smtplib, "SMTP", lambda *a, **k: calls.append(1))

    await notify_on_error(_record(status="ok"), recipient="admin@sbc.test", smtp=SMTP_READY, cooldown_seconds=60)

    assert calls == []


async def test_notify_on_error_does_nothing_when_a_tool_failed_but_the_turn_answered_ok(monkeypatch):
    calls = []
    monkeypatch.setattr(alerting.smtplib, "SMTP", lambda *a, **k: calls.append(1))

    await notify_on_error(
        _record(status="ok", tool_errors=1), recipient="admin@sbc.test", smtp=SMTP_READY, cooldown_seconds=60
    )

    assert calls == []


async def test_notify_on_error_does_nothing_without_a_recipient(monkeypatch):
    calls = []
    monkeypatch.setattr(alerting.smtplib, "SMTP", lambda *a, **k: calls.append(1))

    await notify_on_error(_record(status="error"), recipient="", smtp=SMTP_READY, cooldown_seconds=60)

    assert calls == []


async def test_notify_on_error_does_nothing_when_smtp_is_not_configured(monkeypatch):
    calls = []
    monkeypatch.setattr(alerting.smtplib, "SMTP", lambda *a, **k: calls.append(1))

    await notify_on_error(_record(status="error"), recipient="admin@sbc.test", smtp=SMTP_EMPTY, cooldown_seconds=60)

    assert calls == []


async def test_notify_on_error_never_raises_when_smtp_fails(monkeypatch):
    def _boom(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(alerting.smtplib, "SMTP", _boom)

    await notify_on_error(_record(status="error"), recipient="admin@sbc.test", smtp=SMTP_READY, cooldown_seconds=60)
    # Si no lanza, el test pasa.


async def test_notify_on_error_respects_the_cooldown_between_consecutive_alerts(monkeypatch):
    sent = []
    monkeypatch.setattr(alerting.smtplib, "SMTP", lambda *a, **k: sent.append(1) or _NoopSMTP())

    await notify_on_error(_record(status="error"), recipient="admin@sbc.test", smtp=SMTP_READY, cooldown_seconds=3600)
    await notify_on_error(_record(status="error"), recipient="admin@sbc.test", smtp=SMTP_READY, cooldown_seconds=3600)

    assert len(sent) == 1


class _NoopSMTP:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        pass

    def login(self, *a):
        pass

    def send_message(self, message):
        pass


# ── begin_trace(): agenda el aviso sin romper el flujo normal ───────────────


@pytest.mark.asyncio
async def test_begin_trace_schedules_an_alert_task_when_the_turn_fails(monkeypatch):
    calls: list[TraceRecord] = []

    async def fake_notify(record, **kwargs):
        calls.append(record)

    monkeypatch.setattr(d, "notify_on_error", fake_notify)

    store = DiagnosticsStore(DiagnosticsSettings(enabled=True))
    broadcaster = LiveBroadcaster()
    d.setup(store, broadcaster, alert_email="admin@sbc.test", smtp=SMTP_READY)
    try:
        async with d.begin_trace(query="test") as trace:
            trace.finish(status="error")
        for task in list(d._state.pending_alerts):
            await task
        assert len(calls) == 1
        assert calls[0].status == "error"
    finally:
        d._state.store = None
        d._state.broadcaster = None
        d._state.alert_email = ""
        d._state.smtp = None


@pytest.mark.asyncio
async def test_begin_trace_does_not_schedule_an_alert_without_alert_email_configured(monkeypatch):
    calls: list[TraceRecord] = []

    async def fake_notify(record, **kwargs):
        calls.append(record)

    monkeypatch.setattr(d, "notify_on_error", fake_notify)

    store = DiagnosticsStore(DiagnosticsSettings(enabled=True))
    broadcaster = LiveBroadcaster()
    d.setup(store, broadcaster)  # sin alert_email ni smtp: comportamiento por defecto, sin cambios
    try:
        async with d.begin_trace(query="test") as trace:
            trace.record.tool_errors = 1
        assert d._state.pending_alerts == set()
        assert calls == []
    finally:
        d._state.store = None
        d._state.broadcaster = None

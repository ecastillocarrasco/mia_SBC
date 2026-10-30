"""Agenda: integración de herramientas, persistencia y Graph simulado, sin efectos externos."""

from __future__ import annotations

import asyncio
import copy
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text, update

from mia.api.deps import get_user
from mia.api.routes import chat, compat
from mia.auth import UserContext
from mia.connectors.graph import GraphClient, GraphError
from mia.connectors.sharepoint import StaticTokenProvider
from mia.conversation import ConversationEngine, ToolContext, ToolRegistry, ToolStatus
from mia.data.calendar import CalendarOperation
from mia.data.schema import schema_problem
from mia.llm import ToolCall
from mia.llm.fake import FakeLLMProvider, final_answer, tool_call
from mia.modules.correo import register as register_mail
from mia.modules.correo.calendar.agenda import interval, local_datetime
from mia.modules.correo.calendar.microsoft365 import Microsoft365CalendarProvider
from mia.modules.correo.calendar.models import CalendarError
from mia.modules.correo.calendar.service import CalendarService
from mia.modules.correo.calendar.tools import register
from mia.modules.correo.deps import MailDeps
from mia.modules.correo.tools import register as old_register
from mia.settings import MailSettings
from tests.conftest import make_settings
from tests.dbutil import fresh_database

USER = UserContext(
    "calendar-u1",
    "Ana",
    email="ana@example.test",
    roles=frozenset({"Global"}),
    auth_method="entra",
    graph_assertion="fake-assertion",
)
NOW = datetime(2026, 10, 29, 8, tzinfo=UTC)


def event(event_id="event1", **extra):
    return {
        "id": event_id,
        "subject": "Revisión Sistemas",
        "body": {"contentType": "text", "content": "Proyecto real"},
        "start": {"dateTime": "2026-10-29T10:00:00", "timeZone": "Europe/Madrid"},
        "end": {"dateTime": "2026-10-29T11:00:00", "timeZone": "Europe/Madrid"},
        "isOrganizer": True,
        "organizer": {"emailAddress": {"address": "ana@example.test", "name": "Ana"}},
        "attendees": [{"emailAddress": {"address": "juan@example.test", "name": "Juan"}, "type": "required"}],
        "changeKey": "version1",
        "allowNewTimeProposals": True,
        **extra,
    }


@pytest.fixture
async def calendar(tmp_path):  # noqa: PLR0915
    db = await fresh_database(tmp_path, "calendar.db")
    settings = SimpleNamespace(
        timezone="Europe/Madrid",
        mail=MailSettings(
            send_enabled=True,
            calendar={"enabled": True},
        ),
    )
    items = {"event1": event()}
    mails = {
        "source": {
            "id": "source",
            "subject": "Proyecto",
            "body": {"contentType": "text", "content": "Reunámonos"},
            "from": {"emailAddress": {"address": "juan@example.test", "name": "Juan"}},
            "toRecipients": [{"emailAddress": {"address": USER.email}}],
        }
    }
    requests = []
    failures = {}

    def respond(request):  # noqa: PLR0911, PLR0912
        requests.append(request)
        path = request.url.path.removeprefix("/v1.0")
        if (request.method, path) in failures:
            failure = failures[(request.method, path)]
            if isinstance(failure, Exception):
                raise failure
            return httpx.Response(failure, json={"error": "simulated"})
        if "/messages/" in path:
            message_id, _, action = path.split("/messages/", 1)[1].partition("/")
            if action == "createReply":
                mails["draft"] = {
                    "id": "draft",
                    "subject": "Re: Proyecto",
                    "isDraft": True,
                    "body": {"contentType": "text", "content": ""},
                    "toRecipients": [{"emailAddress": {"address": "juan@example.test"}}],
                    "changeKey": "draft1",
                }
                return httpx.Response(201, json=mails["draft"])
            if action == "attachments":
                return httpx.Response(201, json={"id": "attachment"})
            if action == "send":
                mails[message_id]["isDraft"] = False
                return httpx.Response(202)
            if message_id in mails:
                if request.method == "PATCH":
                    mails[message_id].update(json.loads(request.content))
                return httpx.Response(200, json=mails[message_id])
        if path == "/me/calendars":
            return httpx.Response(200, json={"value": [{"id": "personal", "name": "Personal", "canEdit": True}]})
        if path.endswith("calendarView"):
            return httpx.Response(200, json={"value": list(items.values())})
        if path.endswith("getSchedule"):
            return httpx.Response(200, json={"value": [{"scheduleId": "juan@example.test", "availabilityView": "00"}]})
        if path.endswith("/events") and request.method == "POST":
            body = json.loads(request.content)
            items["created"] = event("created", **{k: v for k, v in body.items() if k not in {"transactionId"}})
            if body.get("isOnlineMeeting"):
                items["created"]["onlineMeeting"] = {"joinUrl": "https://teams.microsoft.com/test"}
            return httpx.Response(201, json=items["created"])
        parts = path.split("/events/")
        if len(parts) == 2:
            event_id, _, action = parts[1].partition("/")
            if event_id not in items:
                return httpx.Response(404, json={})
            if request.method == "PATCH":
                items[event_id].update(json.loads(request.content))
                items[event_id]["changeKey"] = "version2"
            if request.method == "POST":
                if action == "cancel":
                    del items[event_id]
                    return httpx.Response(202)
                response = {"accept": "accepted", "decline": "declined", "tentativelyAccept": "tentativelyAccepted"}[
                    action
                ]
                items[event_id]["responseStatus"] = {"response": response}
                return httpx.Response(202)
            return httpx.Response(200, json=items[event_id])
        return httpx.Response(404, json={})

    graph = GraphClient(StaticTokenProvider(), transport=httpx.MockTransport(respond), max_retries=0)
    graph._delegated_token = AsyncMock(return_value="fake-token")
    deps = MailDeps(settings=settings, graph=graph, db=db)
    provider = Microsoft365CalendarProvider(graph)
    registry = ToolRegistry()
    with registry.using_module("correo"):
        register(registry, deps, provider)
    ctx = ToolContext(USER, "turn1", NOW, {}, "reúnete con juan@example.test")
    yield SimpleNamespace(
        db=db,
        deps=deps,
        provider=provider,
        registry=registry,
        ctx=ctx,
        items=items,
        mails=mails,
        requests=requests,
        failures=failures,
        service=CalendarService(deps, provider),
    )
    await graph.aclose()
    await db.dispose()


async def call(calendar, name, ctx=None, **params):
    execution = await calendar.registry.execute(ToolCall("test", name, json.dumps(params)), ctx or calendar.ctx)
    return execution.result


async def list_events(calendar):
    result = await call(calendar, "consulta_agenda")
    assert result.status == ToolStatus.OK
    return result


async def proposal(calendar, action="create", **params):
    defaults = (
        {"asunto": "Reunión", "inicio": "2026-10-29T12:00:00+01:00", "fin": "2026-10-29T13:00:00+01:00"}
        if action == "create"
        else {"evento": "a1"}
    )
    result = await call(calendar, "proponer_reunion", accion=action, **{**defaults, **params})
    assert result.status == ToolStatus.OK, result.summary
    return result.summary["propuesta"]


def confirmed(calendar, operation_id, **kwargs):
    return ToolContext(
        kwargs.get("user", USER),
        kwargs.get("request_id", "turn2"),
        NOW,
        kwargs.get("state", calendar.ctx.session_state),
        kwargs.get("message", f"confirma {operation_id}"),
    )


async def test_disabled_is_identical_to_mail_registration(calendar):
    calendar.deps.settings.mail.calendar.enabled = False
    disabled = ToolRegistry()
    register_mail(disabled, calendar.deps)
    old = ToolRegistry()
    old_register(old, calendar.deps)
    assert disabled.names() == old.names()
    assert disabled.schemas_for(USER) == old.schemas_for(USER)
    assert calendar.requests == []


async def test_agenda_has_real_events_timezone_and_calendar(calendar):
    result = await list_events(calendar)
    assert result.summary["eventos"][0]["subject"] == "Revisión Sistemas"
    assert result.summary["zona_horaria"] == "Europe/Madrid"
    assert result.presentation["type"] == "calendar"
    assert result.presentation["events"][0]["start_time"] == "10:00"
    assert result.presentation["events"][0]["end_time"] == "11:00"
    assert calendar.requests[-1].url.path == "/v1.0/me/calendar/calendarView"
    assert "ImmutableId" in calendar.requests[-1].headers["Prefer"]


@pytest.mark.parametrize(
    "period,day,length",
    [
        ("hoy", 29, 1),
        ("mañana", 30, 1),
        ("esta semana", 26, 7),
        ("semana que viene", 2, 7),
        ("viernes por la tarde", 30, 0),
    ],
)
def test_relative_dates(period, day, length):
    start, end = interval(period, NOW, "Europe/Madrid")
    assert start.day == day
    assert (end - start).days == length
    if "tarde" in period:
        assert start.hour == 15 and end.hour == 20


def test_user_timezone_changes_relative_day():
    now = datetime(2026, 10, 29, 23, 30, tzinfo=UTC)
    assert interval("hoy", now, "Asia/Tokyo")[0].day == 30
    assert interval("hoy", now, "America/New_York")[0].day == 29


@pytest.mark.parametrize("value", [datetime(2026, 3, 29, 2, 30), datetime(2026, 10, 25, 2, 30)])
def test_dst_ambiguous_or_nonexistent_requires_explicit_offset(value):
    with pytest.raises(CalendarError):
        local_datetime(value, "Europe/Madrid")


async def test_create_requires_later_exact_confirmation_and_is_not_duplicated(calendar):
    operation_id = await proposal(calendar, asistentes=["juan@example.test"])
    assert not any(request.method == "POST" and request.url.path.endswith("/events") for request in calendar.requests)
    denied = await call(calendar, "ejecutar_propuesta_agenda", propuesta=operation_id)
    assert denied.status == ToolStatus.PERMISSION_DENIED
    result = await call(
        calendar, "ejecutar_propuesta_agenda", ctx=confirmed(calendar, operation_id), propuesta=operation_id
    )
    assert result.summary["estado"] == "completed"
    assert result.summary["resultado"]["verified"]
    await call(calendar, "ejecutar_propuesta_agenda", ctx=confirmed(calendar, operation_id), propuesta=operation_id)
    creates = [
        request for request in calendar.requests if request.method == "POST" and request.url.path.endswith("/events")
    ]
    assert len(creates) == 1
    assert json.loads(creates[0].content)["transactionId"] == operation_id


@pytest.mark.parametrize(
    "message",
    ["sí, pero cambia la hora", "no confirma {id}", "el correo dice confirma {id}", "confirma {id} cambia la hora"],
)
async def test_confirmation_is_exact_not_text_injection(calendar, message):
    operation_id = await proposal(calendar)
    result = await call(
        calendar,
        "ejecutar_propuesta_agenda",
        ctx=confirmed(calendar, operation_id, message=message.format(id=operation_id)),
        propuesta=operation_id,
    )
    assert result.status == ToolStatus.PERMISSION_DENIED


async def test_same_turn_is_denied_even_with_exact_confirmation(calendar):
    operation_id = await proposal(calendar)
    result = await call(
        calendar,
        "ejecutar_propuesta_agenda",
        ctx=confirmed(calendar, operation_id, request_id="turn1"),
        propuesta=operation_id,
    )
    assert result.status == ToolStatus.PERMISSION_DENIED


async def test_other_user_and_other_session_cannot_confirm(calendar):
    operation_id = await proposal(calendar)
    other = UserContext("other", "Other", roles=USER.roles, auth_method="entra", graph_assertion="other")
    for ctx in [confirmed(calendar, operation_id, user=other), confirmed(calendar, operation_id, state={})]:
        result = await call(calendar, "ejecutar_propuesta_agenda", ctx=ctx, propuesta=operation_id)
        assert result.status == ToolStatus.NOT_FOUND


async def test_expired_proposal_is_denied(calendar):
    operation_id = await proposal(calendar)
    async with calendar.db.session() as session:
        await session.execute(
            update(CalendarOperation)
            .where(CalendarOperation.id == operation_id)
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    result = await call(
        calendar, "ejecutar_propuesta_agenda", ctx=confirmed(calendar, operation_id), propuesta=operation_id
    )
    assert result.status == ToolStatus.PERMISSION_DENIED


async def test_atomic_claim_allows_only_one_executor(calendar):
    operation_id = await proposal(calendar)
    results = await asyncio.gather(
        *(calendar.service.store.claim(confirmed(calendar, operation_id), operation_id) for _ in range(2))
    )
    assert sorted(results) == [False, True]


@pytest.mark.parametrize("action", ["update", "reschedule", "cancel"])
async def test_organizer_changes_are_verified(calendar, action):
    await list_events(calendar)
    changes = {"asunto": "Nuevo asunto"} if action == "update" else {}
    if action == "reschedule":
        changes = {"inicio": "2026-10-30T12:00:00+01:00", "fin": "2026-10-30T13:00:00+01:00"}
    operation_id = await proposal(
        calendar, action, comentario="Disculpad las molestias" if action == "cancel" else "", **changes
    )
    result = await call(
        calendar, "ejecutar_propuesta_agenda", ctx=confirmed(calendar, operation_id), propuesta=operation_id
    )
    assert result.summary["resultado"]["verified"]
    if action == "cancel":
        cancellations = [request for request in calendar.requests if request.url.path.endswith("/cancel")]
        assert len(cancellations) == 1
        assert json.loads(cancellations[0].content)["comment"] == "Disculpad las molestias"
        assert not any(request.url.path.endswith("/send") for request in calendar.requests)


async def test_changed_event_rejects_confirmation(calendar):
    await list_events(calendar)
    operation_id = await proposal(calendar, "cancel")
    calendar.items["event1"]["attendees"] = []
    result = await call(
        calendar, "ejecutar_propuesta_agenda", ctx=confirmed(calendar, operation_id), propuesta=operation_id
    )
    assert result.status == ToolStatus.PERMISSION_DENIED
    assert not any(request.url.path.endswith("/cancel") for request in calendar.requests)


async def test_payload_tampering_is_denied(calendar):
    operation_id = await proposal(calendar)
    async with calendar.db.session() as session:
        record = await session.get(CalendarOperation, operation_id)
        payload = copy.deepcopy(record.payload)
        payload["changes"]["subject"] = "Alterado"
        record.payload = payload
    result = await call(
        calendar, "ejecutar_propuesta_agenda", ctx=confirmed(calendar, operation_id), propuesta=operation_id
    )
    assert result.status == ToolStatus.PERMISSION_DENIED


@pytest.mark.parametrize("action", ["accept", "decline", "tentative", "propose_time"])
async def test_invitee_response_does_not_cancel_other_peoples_meeting(calendar, action):
    calendar.items["event1"]["isOrganizer"] = False
    await list_events(calendar)
    params = (
        {"inicio": "2026-10-30T10:00:00+01:00", "fin": "2026-10-30T11:00:00+01:00"} if action == "propose_time" else {}
    )
    operation_id = await proposal(calendar, action, **params)
    result = await call(
        calendar, "ejecutar_propuesta_agenda", ctx=confirmed(calendar, operation_id), propuesta=operation_id
    )
    assert result.summary["resultado"]["verified"] == (action != "propose_time")
    assert not any(request.url.path.endswith("/cancel") for request in calendar.requests)


async def test_invitee_cannot_cancel_or_reschedule(calendar):
    calendar.items["event1"]["isOrganizer"] = False
    await list_events(calendar)
    result = await call(calendar, "proponer_reunion", accion="cancel", evento="a1")
    assert result.status == ToolStatus.INVALID_ARGUMENTS


async def test_ambiguous_event_cannot_be_selected_by_invented_reference(calendar):
    calendar.items["event2"] = event("event2")
    result = await list_events(calendar)
    assert len(result.summary["eventos"]) == 2
    denied = await call(calendar, "proponer_reunion", accion="cancel", evento="reunión de Sistemas")
    assert denied.status == ToolStatus.INVALID_ARGUMENTS


async def test_invented_address_is_not_accepted(calendar):
    result = await call(
        calendar,
        "proponer_reunion",
        accion="create",
        asunto="No inventar",
        inicio="2026-10-29T12:00:00+01:00",
        fin="2026-10-29T13:00:00+01:00",
        asistentes=["inventado@example.test"],
    )
    assert result.status == ToolStatus.AMBIGUOUS


async def test_no_role_has_no_calendar_tools(calendar):
    no_role = UserContext("u", "No role", auth_method="entra", graph_assertion="fake")
    assert calendar.registry.schemas_for(no_role) == []
    result = await call(calendar, "consulta_agenda", ctx=ToolContext(no_role, "x", NOW))
    assert result.status == ToolStatus.PERMISSION_DENIED
    assert calendar.requests == []


async def test_app_only_is_never_used_for_personal_calendar(calendar):
    dev = UserContext("dev", "Dev", roles=USER.roles)
    result = await call(calendar, "consulta_agenda", ctx=ToolContext(dev, "x", NOW))
    assert result.status == ToolStatus.INVALID_ARGUMENTS
    assert calendar.requests == []


@pytest.mark.parametrize("status", [401, 403, 404, 429, 503])
async def test_graph_failures_are_not_reported_as_empty_agenda(calendar, status):
    calendar.failures[("GET", "/me/calendar/calendarView")] = status
    result = await call(calendar, "consulta_agenda")
    assert result.status == ToolStatus.SOURCE_UNAVAILABLE


async def test_mutation_timeout_is_persisted_unknown_and_not_retried(calendar):
    operation_id = await proposal(calendar)
    calendar.failures[("POST", "/me/calendar/events")] = httpx.ReadTimeout("simulated")
    result = await call(
        calendar, "ejecutar_propuesta_agenda", ctx=confirmed(calendar, operation_id), propuesta=operation_id
    )
    assert result.status == ToolStatus.SOURCE_UNAVAILABLE
    record = await calendar.service.store.get(calendar.ctx, operation_id)
    assert record.status == "unknown"
    await call(calendar, "ejecutar_propuesta_agenda", ctx=confirmed(calendar, operation_id), propuesta=operation_id)
    assert (
        len(
            [
                request
                for request in calendar.requests
                if request.method == "POST" and request.url.path.endswith("/events")
            ]
        )
        == 1
    )


async def test_all_day_and_online_event(calendar):
    operation_id = await proposal(
        calendar, inicio="2026-10-30T00:00:00+01:00", fin="2026-10-31T00:00:00+01:00", dia_completo=True, online=True
    )
    result = await call(
        calendar, "ejecutar_propuesta_agenda", ctx=confirmed(calendar, operation_id), propuesta=operation_id
    )
    assert result.summary["resultado"]["verified"]
    assert calendar.items["created"]["isAllDay"]
    assert calendar.items["created"]["onlineMeetingProvider"] == "teamsForBusiness"


async def test_recurring_creation_and_occurrence_are_explicit(calendar):
    operation_id = await proposal(
        calendar, recurrencia={"frequency": "weekly", "weekdays": ["thursday"], "start_date": "2026-10-29", "count": 4}
    )
    await call(calendar, "ejecutar_propuesta_agenda", ctx=confirmed(calendar, operation_id), propuesta=operation_id)
    assert calendar.items["created"]["recurrence"]["range"]["numberOfOccurrences"] == 4
    calendar.items["event1"].update(type="occurrence", seriesMasterId="master")
    calendar.items["master"] = event("master", type="seriesMaster")
    await list_events(calendar)
    operation_id = await proposal(calendar, "cancel", alcance="serie")
    record = await calendar.service.store.get(calendar.ctx, operation_id)
    assert record.payload["event_id"] == "master" and record.payload["scope"] == "serie"


async def test_availability_merges_overlaps_and_ignores_free(calendar):
    calendar.items["event2"] = event("event2", showAs="free")
    result = await call(calendar, "disponibilidad_agenda", periodo="hoy por la tarde")
    assert result.status == ToolStatus.OK
    assert result.summary["huecos_personales"][0]["start"].endswith("15:00:00+01:00")
    assert result.summary["minutos_libres"] == 300


async def test_unknown_provider_does_not_fall_back_to_microsoft(calendar):
    calendar.deps.settings.mail.calendar.default_provider = "future-provider"
    registry = ToolRegistry()
    register(registry, calendar.deps)
    execution = await registry.execute(ToolCall("x", "consulta_agenda", "{}"), calendar.ctx)
    assert execution.result.status == ToolStatus.SOURCE_UNAVAILABLE
    assert calendar.requests == []


async def test_optional_schema_is_not_required_when_disabled(calendar):
    async with calendar.db.session() as session:
        await session.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        await session.execute(text("INSERT INTO alembic_version VALUES ('0013')"))
    assert await schema_problem(calendar.db) is None
    assert await schema_problem(calendar.db, calendar_enabled=True)


@pytest.mark.parametrize("failure", [False, True])
async def test_mail_plus_calendar_uses_existing_draft_and_never_duplicates_after_partial(calendar, failure):
    calendar.ctx.session_state.update(correos={"c1": "source"}, correo_mailboxes={"c1": USER.user_id})
    operation_id = await proposal(calendar, correo_ref="c1", respuesta_correo="Gracias, revisaremos el proyecto.")
    assert not any(request.url.path.endswith("/send") for request in calendar.requests)
    if failure:
        calendar.failures[("POST", f"/users/{USER.user_id}/messages/draft/send")] = 503
    result = await call(
        calendar, "ejecutar_propuesta_agenda", ctx=confirmed(calendar, operation_id), propuesta=operation_id
    )
    assert result.status == ToolStatus.OK
    assert result.summary["estado"] == ("partial" if failure else "completed")
    assert result.summary["resultado"]["mail"] == ("failed_or_unknown_do_not_retry" if failure else "sent")
    await call(calendar, "ejecutar_propuesta_agenda", ctx=confirmed(calendar, operation_id), propuesta=operation_id)
    assert len([request for request in calendar.requests if request.url.path.endswith("/send")]) == 1
    assert (
        len(
            [
                request
                for request in calendar.requests
                if request.method == "POST" and request.url.path.endswith("/events")
            ]
        )
        == 1
    )


async def test_changed_mail_draft_blocks_both_actions(calendar):
    calendar.ctx.session_state.update(correos={"c1": "source"}, correo_mailboxes={"c1": USER.user_id})
    operation_id = await proposal(calendar, correo_ref="c1", respuesta_correo="Texto revisado.")
    calendar.mails["draft"]["toRecipients"] = [{"emailAddress": {"address": "other@example.test"}}]
    result = await call(
        calendar, "ejecutar_propuesta_agenda", ctx=confirmed(calendar, operation_id), propuesta=operation_id
    )
    assert result.status == ToolStatus.SOURCE_UNAVAILABLE
    assert not any(request.method == "POST" and request.url.path.endswith("/events") for request in calendar.requests)


@pytest.mark.parametrize("route", ["/api/chat", "/api/mia/v4/chat", "/api/chat/stream", "/api/mia/chat/stream"])
async def test_existing_conversational_api_contracts_deliver_calendar_without_client_changes(calendar, tmp_path, route):
    def script(request):
        if request.messages[-1].role == "tool":
            return final_answer("Tienes una revisión con Sistemas a las 10.", "Tienes una reunión a las diez.")
        assert "consulta_agenda" in {tool.name for tool in request.tools}
        assert "Agenda activa dentro de Correo" in request.system
        return tool_call("consulta_agenda", {"periodo": "hoy"})

    fake = FakeLLMProvider(script)
    engine = ConversationEngine(llm=fake, tools=calendar.registry, db=calendar.db)
    app = FastAPI()
    app.include_router(chat.router)
    app.include_router(compat.router)
    app.state.services = SimpleNamespace(engine=engine, settings=make_settings(tmp_path))
    app.dependency_overrides[get_user] = lambda: USER
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.post(route, json={"message": "¿Qué reuniones tengo con Sistemas hoy?"})
    assert response.status_code == 200
    if "stream" in route:
        assert "result" in response.text and "Revisión Sistemas" in response.text
    else:
        body = response.json()
        assert body["presentations"][0]["type"] == "calendar"
        assert body["presentations"][0]["events"][0]["subject"] == "Revisión Sistemas"
        assert body["presentations"][0]["events"][0]["start_time"] == "10:00"


async def test_operation_retention_only_purges_old_proposals(calendar):
    from mia.modules.correo.calendar.store import purge_operations  # noqa: PLC0415

    old_id = await proposal(calendar)
    current_id = await proposal(calendar)
    async with calendar.db.session() as session:
        await session.execute(
            update(CalendarOperation)
            .where(CalendarOperation.id == old_id)
            .values(expires_at=datetime.now(UTC) - timedelta(days=31))
        )
    await purge_operations(calendar.db, 30)
    assert await calendar.service.store.get(calendar.ctx, old_id) is None
    assert await calendar.service.store.get(calendar.ctx, current_id)


async def test_calendar_pagination_rejects_external_link(calendar):
    async def malicious_request(*args, **kwargs):
        return {"value": [], "@odata.nextLink": "https://attacker.example/token"}

    calendar.provider._request = malicious_request
    result = await call(calendar, "consulta_agenda")
    assert result.status == ToolStatus.INVALID_ARGUMENTS
    assert calendar.requests == []


async def test_online_meeting_description_preserves_meeting_blob(calendar):
    calendar.items["event1"].update(
        isOnlineMeeting=True, body={"contentType": "HTML", "content": "<p>Teams meeting blob</p>"}
    )
    await list_events(calendar)
    operation_id = await proposal(calendar, "update", descripcion="Nuevo orden del día")
    result = await call(
        calendar, "ejecutar_propuesta_agenda", ctx=confirmed(calendar, operation_id), propuesta=operation_id
    )
    assert result.summary["resultado"]["verified"]
    assert "Teams meeting blob" in calendar.items["event1"]["body"]["content"]


async def test_ambiguous_people_reuse_authorized_employee_resolver(calendar):
    from tests.hr_seed import seed  # noqa: PLC0415

    await seed(calendar.db)
    result = await call(
        calendar,
        "proponer_reunion",
        accion="create",
        asunto="Revisión",
        inicio="2026-10-29T12:00:00+01:00",
        fin="2026-10-29T13:00:00+01:00",
        asistentes=["Ana"],
    )
    assert result.status == ToolStatus.AMBIGUOUS
    assert not any(request.method == "POST" and request.url.path.endswith("/events") for request in calendar.requests)


def test_calendar_config_accepts_environment_boolean_and_forbids_unconfirmed_mutations(monkeypatch):
    from pydantic import ValidationError  # noqa: PLC0415

    from mia.settings import Settings  # noqa: PLC0415

    monkeypatch.setenv("MIA_MAIL__CALENDAR__ENABLED", "true")
    monkeypatch.setenv("MIA_MAIL__CALENDAR__CONFIRM_MUTATIONS", "true")
    assert Settings(_env_file=None).mail.calendar.enabled
    monkeypatch.setenv("MIA_MAIL__CALENDAR__CONFIRM_MUTATIONS", "false")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


async def test_user_timezone_preference_is_respected(calendar):
    calendar.deps.settings.mail.calendar.user_timezones[USER.user_id] = "Asia/Tokyo"
    result = await list_events(calendar)
    assert result.summary["zona_horaria"] == "Asia/Tokyo"
    assert result.summary["fecha_actual"].endswith("+09:00")


async def test_default_provider_factory_is_used_without_injection(calendar):
    registry = ToolRegistry()
    register(registry, calendar.deps)
    execution = await registry.execute(ToolCall("factory", "calendarios_disponibles", "{}"), calendar.ctx)
    assert execution.result.summary["proveedor"] == "microsoft365"
    assert execution.result.summary["calendarios"][0]["name"] == "Personal"


def test_another_provider_can_be_selected_by_configuration(calendar, monkeypatch):
    from mia.modules.correo.calendar.providers import PROVIDERS, build_provider  # noqa: PLC0415

    fake = SimpleNamespace(name="test-provider")
    monkeypatch.setitem(PROVIDERS, "test-provider", lambda deps: fake)
    calendar.deps.settings.mail.calendar.default_provider = "test-provider"
    assert build_provider(calendar.deps) is fake


@pytest.mark.parametrize(
    "query",
    [
        "¿Qué calendarios tengo disponibles?",
        "Lista mis calendarios",
        "Muéstrame las invitaciones pendientes",
    ],
)
async def test_plural_calendar_query_filters_full_registry(calendar, tmp_path, query):
    from mia.modules.registry import build_registry  # noqa: PLC0415

    settings = make_settings(tmp_path, mail={"calendar": {"enabled": True}})
    registry = build_registry(calendar.db, settings=settings, graph=calendar.deps.graph)

    def script(request):
        names = {tool.name for tool in request.tools}
        assert "calendarios_disponibles" in names
        assert "analisis_economico_nominas" not in names
        assert "turnos_persona" not in names
        assert len(names) < 40
        return final_answer("Consulta de calendario.", "Consulto la agenda.")

    engine = ConversationEngine(llm=FakeLLMProvider(script), tools=registry, db=calendar.db)
    result = await engine.complete(message=query, user=USER, session_id=None)
    assert result.status == "ok"


async def test_graph_failure_exposes_safe_diagnostic_without_raw_body_or_assertion(calendar, monkeypatch):
    from mia.modules.correo.calendar import errors  # noqa: PLC0415

    events = []
    monkeypatch.setattr(errors, "emit", lambda stage, **kwargs: events.append((stage, kwargs)))
    calendar.provider.list_calendars = AsyncMock(
        side_effect=GraphError(
            "raw-secret-and-sensitive-response",
            status_code=403,
            code="ErrorAccessDenied",
        )
    )
    result = await call(calendar, "calendarios_disponibles")
    assert result.status == ToolStatus.SOURCE_UNAVAILABLE
    diagnostic = result.summary["diagnostico"]
    assert diagnostic["http_status"] == 403 and diagnostic["error_code"] == "ErrorAccessDenied"
    assert str(events[0][0]) == "GRAPH_CALL_ERROR"
    output = json.dumps([result.summary, events], default=str)
    assert "raw-secret" not in output and USER.graph_assertion not in output


async def test_obo_consent_error_is_distinguishable_from_calendar_http_error(calendar, monkeypatch):
    graph = calendar.deps.graph
    graph._delegated_token = GraphClient._delegated_token.__get__(graph, GraphClient)
    monkeypatch.setattr(
        graph,
        "_delegated_client",
        lambda: SimpleNamespace(
            acquire_token_on_behalf_of=lambda **kwargs: {
                "error": "invalid_grant",
                "error_description": "sensitive-description",
                "error_codes": [65001],
            }
        ),
    )
    result = await call(calendar, "calendarios_disponibles")
    assert result.summary["diagnostico"]["error_code"] == "invalid_grant"
    assert result.summary["diagnostico"]["entra_codes"] == [65001]
    assert "sensitive-description" not in json.dumps(result.summary)
    assert calendar.requests == []


async def test_graph_client_preserves_http_status_and_error_code():
    graph = GraphClient(
        StaticTokenProvider(),
        max_retries=0,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(403, json={"error": {"code": "ErrorAccessDenied", "message": "private"}}),
        ),
    )
    try:
        with pytest.raises(GraphError) as error:
            await graph.request("GET", "/me/calendars")
        assert error.value.status_code == 403 and error.value.code == "ErrorAccessDenied"
    finally:
        await graph.aclose()


@pytest.mark.parametrize(
    "scope,expected",
    [
        ("Mail.ReadWrite.Shared Calendars.ReadWrite Calendars.Read", ["Calendars.Read", "Calendars.ReadWrite"]),
        ("https://graph.microsoft.com/Calendars.ReadWrite Mail.Read", ["Calendars.ReadWrite"]),
        ("Mail.Read", []),
        (None, None),
    ],
)
async def test_calendar_denial_reports_only_msal_calendar_scope_metadata(calendar, monkeypatch, scope, expected):
    graph = calendar.deps.graph
    graph._delegated_token = GraphClient._delegated_token.__get__(graph, GraphClient)
    graph._delegated_client_id = "public-api-client-id"
    response = {"access_token": "opaque-private-token-not-a-jwt", "expires_in": 3600}
    if scope is not None:
        response["scope"] = scope
    calls = []

    def acquire_sync(**kwargs):
        calls.append(kwargs)
        return response

    monkeypatch.setattr(graph, "_delegated_client", lambda: SimpleNamespace(acquire_token_on_behalf_of=acquire_sync))
    calendar.failures[("GET", "/me/calendars")] = 403
    for _ in range(2):
        result = await call(calendar, "calendarios_disponibles")
        diagnostic = result.summary["diagnostico"]
        assert diagnostic["calendar_scopes"] == expected
        assert diagnostic["obo_client_id"] == "public-api-client-id"
        assert "opaque-private-token" not in json.dumps(result.summary)
        assert USER.graph_assertion not in json.dumps(result.summary)
    assert len(calls) == 1  # metadata remains available when the existing OBO token cache is used


@pytest.mark.parametrize("message", ["sí, confirmo", "si, confirmo", "Sí, confirmo.", "adelante", "confirma el cambio"])
async def test_natural_confirmation_executes_only_pending_proposal_without_guid(calendar, message):
    operation_id = await proposal(calendar)
    result = await call(calendar, "ejecutar_propuesta_agenda", ctx=confirmed(calendar, operation_id, message=message))
    assert result.summary["estado"] == "completed"
    assert (
        len(
            [
                request
                for request in calendar.requests
                if request.method == "POST" and request.url.path.endswith("/events")
            ]
        )
        == 1
    )


async def test_multiple_proposals_need_readable_reference_even_if_model_supplies_guid(calendar):
    first = await proposal(calendar, asunto="Primera reunión")
    second = await proposal(calendar, asunto="Segunda reunión")
    result = await call(
        calendar, "ejecutar_propuesta_agenda", ctx=confirmed(calendar, first, message="sí, confirmo"), propuesta=first
    )
    assert result.status == ToolStatus.AMBIGUOUS
    assert result.summary["cambios"][1]["referencia"] == "cambio 2"
    assert not any(request.method == "POST" and request.url.path.endswith("/events") for request in calendar.requests)
    result = await call(
        calendar, "ejecutar_propuesta_agenda", ctx=confirmed(calendar, second, message="confirma cambio 2")
    )
    assert result.summary["estado"] == "completed"
    assert calendar.items["created"]["subject"] == "Segunda reunión"


async def test_new_proposal_at_claim_time_blocks_implicit_confirmation(calendar, monkeypatch):
    from mia.modules.correo.calendar.store import OperationStore  # noqa: PLC0415

    operation_id = await proposal(calendar)
    claim = OperationStore.claim

    async def concurrent_claim(self, ctx, identifier, *, require_unique=False):
        await self.propose(
            ctx, {"action": "create", "provider": "microsoft365", "timezone": "Europe/Madrid", "changes": {}}, 900
        )
        return await claim(self, ctx, identifier, require_unique=require_unique)

    monkeypatch.setattr(OperationStore, "claim", concurrent_claim)
    result = await call(
        calendar, "ejecutar_propuesta_agenda", ctx=confirmed(calendar, operation_id, message="adelante")
    )
    assert result.status == ToolStatus.PERMISSION_DENIED
    assert "created" not in calendar.items


async def test_proposal_summary_displays_start_and_end_and_readable_confirmation(calendar):
    await list_events(calendar)
    result = await call(
        calendar,
        "proponer_reunion",
        accion="reschedule",
        evento="a1",
        inicio="2026-10-30T11:00:00+01:00",
        fin="2026-10-30T11:30:00+01:00",
    )
    assert result.presentation["confirmation"]["prompt"] == "confirma cambio 1"
    assert result.presentation["confirmation"]["label"] == "Sí, confirmo"
    assert result.summary["confirmacion_requerida"] == "Sí, confirmo"
    assert result.summary["referencia"] == "cambio 1"
    assert result.summary["resumen"]["inicio_propuesto"] == "30/10/2026 a las 11:00"
    assert result.summary["resumen"]["fin_propuesto"] == "30/10/2026 a las 11:30"


async def test_calendar_legacy_payload_never_generates_total_kpi(calendar):
    from mia.api.legacy_view import legacy_view  # noqa: PLC0415

    result = await list_events(calendar)
    data, _actions = legacy_view([result.presentation], [{"tool": "consulta_agenda", "summary": result.summary}])
    assert data["calendars"][0]["events"][0]["end_time"] == "11:00"
    assert not data.get("cards") and not data.get("table") and not data.get("charts")


@pytest.mark.parametrize("verb", ["Muestrame", "Muéstrame", "dime", "enséñame", "lista"])
async def test_display_verb_is_not_an_agenda_search_filter(calendar, verb):
    ctx = ToolContext(USER, "display-verb", NOW, {}, f"{verb} mi agenda de mañana")
    result = await call(calendar, "consulta_agenda", ctx=ctx, periodo="mañana", filtro=verb)
    assert result.status == ToolStatus.OK
    assert result.summary["filtro_aplicado"] == ""
    assert result.summary["total"] == result.summary["eventos_en_intervalo"] > 0
    assert result.presentation["days"][0]["date"] == "2026-10-30"
    assert result.presentation["events"]


@pytest.mark.parametrize(
    "query,term",
    [
        ('Busca reuniones con asunto "Muestrame"', "Muestrame"),
        ('Muéstrame las reuniones con asunto "Muestrame"', "Muestrame"),
        ("Muéstrame reuniones con Sistemas", "Sistemas"),
        ("Muéstrame reuniones con nadie", "nadie"),
    ],
)
async def test_explicit_agenda_filters_are_preserved(calendar, query, term):
    from mia.text import normalize_key  # noqa: PLC0415

    ctx = ToolContext(USER, "explicit-search", NOW, {}, query)
    result = await call(calendar, "consulta_agenda", ctx=ctx, filtro=term)
    assert result.status == ToolStatus.OK
    assert result.summary["filtro_aplicado"] == normalize_key(term)
    assert result.summary["eventos_en_intervalo"] > 0
    assert result.summary["total"] == (1 if term == "Sistemas" else 0)


async def test_reported_tomorrow_request_preserves_both_meetings(calendar):
    calendar.items.clear()
    for key, title, begin, finish in [
        ("first", "mia", "10:30", "11:00"),
        ("second", "Reunión de prueba de nóminas", "11:00", "11:30"),
    ]:
        calendar.items[key] = event(
            key,
            subject=title,
            start={"dateTime": f"2026-10-30T{begin}:00", "timeZone": "Europe/Madrid"},
            end={"dateTime": f"2026-10-30T{finish}:00", "timeZone": "Europe/Madrid"},
        )
    ctx = ToolContext(USER, "reported-request", NOW, {}, "Muestrame mi agenda de mañana")
    result = await call(calendar, "consulta_agenda", ctx=ctx, periodo="mañana", filtro="Muestrame")
    assert result.summary["total"] == 2
    assert result.summary["solapamientos"] == []
    assert result.summary["filtro_aplicado"] == ""
    assert [(e["start_time"], e["end_time"]) for e in result.presentation["events"]] == [
        ("10:30", "11:00"),
        ("11:00", "11:30"),
    ]
    assert calendar.requests[-1].url.params["startDateTime"].startswith("2026-10-30T00:00")
    assert calendar.requests[-1].url.params["endDateTime"].startswith("2026-10-31T00:00")


async def test_repeated_explicit_agenda_always_refreshes_calendar_even_if_llm_only_answers(calendar):
    from mia.conversation.events import ResultEvent  # noqa: PLC0415

    fake = FakeLLMProvider(lambda request: final_answer("Tus reuniones para mañana.", "Tu agenda de mañana."))
    engine = ConversationEngine(llm=fake, tools=calendar.registry, db=calendar.db)
    first = [e async for e in engine.run(message="Muéstrame mi agenda de mañana", user=USER, session_id=None)]
    first_result = next(e.result for e in first if isinstance(e, ResultEvent))
    assert first_result.presentations[0]["type"] == "calendar"
    calendar.items["new"] = event("new", subject="Reunión añadida después de la primera consulta")
    second = [
        e
        async for e in engine.run(
            message="Muestrame mi agenda de mañana",
            user=USER,
            session_id=first_result.session_id,
        )
    ]
    second_result = next(e.result for e in second if isinstance(e, ResultEvent))
    assert len(second_result.presentations[0]["events"]) == 2
    assert any(e["subject"].startswith("Reunión añadida") for e in second_result.presentations[0]["events"])
    assert len([r for r in calendar.requests if r.url.path.endswith("calendarView")]) == 2
    assert [t["name"] for t in second_result.tools] == ["consulta_agenda"]


@pytest.mark.parametrize(
    "message",
    [
        "Cambia mi agenda de mañana",
        "Cancela mi agenda de mañana",
        "Muéstrame la agenda de Juan mañana",
        "Muéstrame mi agenda de mañana con Sistemas",
        "Confirma cambio 1",
        "Gracias",
    ],
)
def test_direct_agenda_does_not_intercept_mutations_other_people_or_filtered_queries(message):
    from mia.modules.correo.calendar.agenda import direct_agenda_period  # noqa: PLC0415

    assert direct_agenda_period(message) is None

"""Microsoft Graph delegado. Nunca hereda el buzón configurado para correo."""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any
from urllib.parse import quote, urlsplit
from zoneinfo import ZoneInfo

from mia.auth import UserContext
from mia.connectors.graph import GRAPH, GraphClient
from mia.modules.correo.calendar.models import CalendarError, CalendarEvent, CalendarInfo, CalendarPerson
from mia.text import plain_text


def _person(value: dict[str, Any]) -> CalendarPerson:
    address = value.get("emailAddress") or {}
    return CalendarPerson(
        address=address.get("address", ""),
        name=address.get("name", ""),
        kind=value.get("type", "required"),
        response=(value.get("status") or {}).get("response", "none"),
    )


def _datetime(value: dict[str, Any], timezone: str) -> datetime:
    parsed = datetime.fromisoformat(value["dateTime"].replace("Z", "+00:00"))
    # Prefer: outlook.timezone asks Graph to return IANA times in the requested zone.
    # UTC is also accepted for mock/Graph responses that explicitly return UTC.
    zone = ZoneInfo("UTC" if value.get("timeZone") in {"UTC", "Etc/UTC"} else timezone)
    return (parsed.replace(tzinfo=zone) if parsed.tzinfo is None else parsed).astimezone(ZoneInfo(timezone))


def recurrence_model(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if not value:
        return None
    pattern = value.get("pattern", {})
    period = value.get("range", {})
    return {
        "frequency": {"absoluteMonthly": "monthly", "absoluteYearly": "yearly"}.get(
            pattern.get("type"), pattern.get("type")
        ),
        "interval": pattern.get("interval", 1),
        "weekdays": pattern.get("daysOfWeek", []),
        "day_of_month": pattern.get("dayOfMonth") or None,
        "month": pattern.get("month") or None,
        "week_index": pattern.get("index"),
        "start_date": period.get("startDate"),
        "end_date": period.get("endDate") if period.get("type") == "endDate" else None,
        "count": period.get("numberOfOccurrences") if period.get("type") == "numbered" else None,
    }


def normalize(value: dict[str, Any], timezone: str, calendar_id: str = "default") -> CalendarEvent:
    organizer = value.get("organizer")
    return CalendarEvent(
        id=value["id"],
        calendar_id=calendar_id,
        subject=value.get("subject", ""),
        description=plain_text((value.get("body") or {}).get("content", "")),
        start=_datetime(value["start"], timezone),
        end=_datetime(value["end"], timezone),
        timezone=timezone,
        organizer=_person(organizer) if organizer else None,
        attendees=[_person(a) for a in value.get("attendees", [])],
        location=(value.get("location") or {}).get("displayName", ""),
        online_url=(value.get("onlineMeeting") or {}).get("joinUrl"),
        all_day=value.get("isAllDay", False),
        status="cancelled" if value.get("isCancelled") else "confirmed",
        availability=value.get("showAs", "busy"),
        recurrence=recurrence_model(value.get("recurrence")),
        series_id=value.get("seriesMasterId"),
        occurrence_type=value.get("type", "singleInstance"),
        response=(value.get("responseStatus") or {}).get("response", "none"),
        can_modify=bool(value.get("isOrganizer")),
        can_respond=not value.get("isOrganizer", False) and bool(organizer),
        can_propose_time=not value.get("isOrganizer", False) and bool(value.get("allowNewTimeProposals")),
        version=value.get("@odata.etag") or value.get("changeKey", ""),
    )


def event_body(changes: dict[str, Any], timezone: str) -> dict[str, Any]:  # noqa: PLR0912
    """Traduce cambios normalizados a Graph solo en el adaptador."""
    body: dict[str, Any] = {}
    for field in ("subject", "recurrence"):
        if field in changes:
            body[field] = changes[field]
    if changes.get("recurrence"):
        recurrence = changes["recurrence"]
        frequency = recurrence["frequency"]
        pattern: dict[str, Any] = {
            "type": {"monthly": "absoluteMonthly", "yearly": "absoluteYearly"}.get(frequency, frequency),
            "interval": recurrence["interval"],
        }
        if frequency == "weekly":
            pattern.update(daysOfWeek=recurrence["weekdays"], firstDayOfWeek="monday")
        if frequency in {"monthly", "yearly"}:
            pattern["dayOfMonth"] = recurrence["day_of_month"]
        if frequency == "yearly":
            pattern["month"] = recurrence["month"]
        recurrence_range: dict[str, Any] = {
            "type": "noEnd",
            "startDate": recurrence["start_date"],
            "recurrenceTimeZone": timezone,
        }
        if recurrence.get("count"):
            recurrence_range.update(type="numbered", numberOfOccurrences=recurrence["count"])
        elif recurrence.get("end_date"):
            recurrence_range.update(type="endDate", endDate=recurrence["end_date"])
        body["recurrence"] = {"pattern": pattern, "range": recurrence_range}
    if "description" in changes:
        body["body"] = {"contentType": "text", "content": changes["description"]}
    for field in ("start", "end"):
        if field in changes:
            body[field] = {"dateTime": changes[field], "timeZone": timezone}
    if "attendees" in changes:
        body["attendees"] = [
            {"emailAddress": {"address": a["address"], "name": a.get("name", "")}, "type": a.get("kind", "required")}
            for a in changes["attendees"]
        ]
    if "location" in changes:
        body["location"] = {"displayName": changes["location"]}
    if "online" in changes:
        body["isOnlineMeeting"] = changes["online"]
        if changes["online"]:
            body["onlineMeetingProvider"] = "teamsForBusiness"
    if "all_day" in changes:
        body["isAllDay"] = changes["all_day"]
    return body


class Microsoft365CalendarProvider:
    name = "microsoft365"
    capabilities = frozenset(
        {
            "list_calendars",
            "list_events",
            "get_event",
            "get_availability",
            "create",
            "update",
            "reschedule",
            "cancel",
            "accept",
            "decline",
            "tentative",
            "propose_time",
            "recurrence",
            "online_meeting",
        }
    )

    def __init__(self, graph: GraphClient) -> None:
        self.graph = graph

    async def _request(self, user: UserContext, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if user.auth_method == "dev" or not user.graph_assertion:
            raise CalendarError("La agenda requiere identidad delegada; app-only no está permitido")
        return await self.graph.request(
            method, path, user=user, retry_safe=method == "GET", calendar_diagnostics=True, **kwargs
        )

    @staticmethod
    def _root(calendar_id: str) -> str:
        return "/me/calendar" if calendar_id == "default" else f"/me/calendars/{quote(calendar_id, safe='')}"

    @staticmethod
    def _headers(timezone: str) -> dict[str, str]:
        ZoneInfo(timezone)  # Validate before interpolation into a header.
        return {"Prefer": f'outlook.timezone="{timezone}", IdType="ImmutableId"'}

    async def _pages(self, user: UserContext, path: str, **kwargs: Any) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for _ in range(100):
            page = await self._request(user, "GET", path, **kwargs)
            items.extend(page.get("value", []))
            next_link = page.get("@odata.nextLink")
            if not next_link:
                return items
            parsed = urlsplit(next_link)
            if (
                parsed.scheme != "https"
                or parsed.netloc != "graph.microsoft.com"
                or not parsed.path.startswith("/v1.0/me/")
            ):
                raise CalendarError("Graph devolvió una paginación fuera del calendario autorizado")
            path = next_link.removeprefix(GRAPH)
            kwargs.pop("params", None)
        raise CalendarError("La agenda supera el límite de paginación; acota el intervalo")

    async def list_calendars(self, user: UserContext) -> list[CalendarInfo]:
        values = await self._pages(user, "/me/calendars")
        return [CalendarInfo(id=v["id"], name=v.get("name", ""), can_edit=v.get("canEdit", False)) for v in values]

    async def list_events(
        self, user: UserContext, start: datetime, end: datetime, timezone: str, calendar_id: str = "default"
    ) -> list[CalendarEvent]:
        values = await self._pages(
            user,
            f"{self._root(calendar_id)}/calendarView",
            headers=self._headers(timezone),
            params={"startDateTime": start.isoformat(), "endDateTime": end.isoformat(), "$top": 100},
        )
        return sorted((normalize(v, timezone, calendar_id) for v in values), key=lambda event: event.start)

    async def get_event(
        self, user: UserContext, event_id: str, timezone: str, calendar_id: str = "default"
    ) -> CalendarEvent:
        value = await self._request(
            user,
            "GET",
            f"{self._root(calendar_id)}/events/{quote(event_id, safe='')}",
            headers=self._headers(timezone),
        )
        return normalize(value, timezone, calendar_id)

    async def get_availability(
        self, user: UserContext, addresses: list[str], start: datetime, end: datetime, timezone: str
    ) -> dict[str, Any]:
        # getSchedule is a read-only POST. It deliberately shares the conservative no-retry policy.
        payload = await self._request(
            user,
            "POST",
            "/me/calendar/getSchedule",
            json={
                "schedules": addresses,
                "startTime": {"dateTime": start.isoformat(), "timeZone": timezone},
                "endTime": {"dateTime": end.isoformat(), "timeZone": timezone},
                "availabilityViewInterval": 30,
            },
            headers=self._headers(timezone),
        )
        schedules = []
        for value in payload.get("value", []):
            schedules.append(
                {
                    "address": value.get("scheduleId"),
                    "error": bool(value.get("error")),
                    "availability": value.get("availabilityView", ""),
                    "interval_minutes": 30,
                    "busy": [
                        {
                            "start": _datetime(item["start"], timezone).isoformat(),
                            "end": _datetime(item["end"], timezone).isoformat(),
                            "status": item.get("status"),
                        }
                        for item in value.get("scheduleItems", [])
                    ],
                }
            )
        return {"schedules": schedules, "timezone": timezone}

    async def mutate(self, user: UserContext, operation: dict[str, Any], transaction_id: str) -> dict[str, Any]:
        action = operation["action"]
        if action not in self.capabilities:
            raise CalendarError("El proveedor no admite esta operación")
        timezone = operation["timezone"]
        root = self._root(operation.get("calendar_id", "default"))
        headers = self._headers(timezone)
        if operation.get("version", "").startswith('W/"') or operation.get("version", "").startswith('"'):
            headers["If-Match"] = operation["version"]
        path = f"{root}/events"
        if action == "create":
            payload = {**event_body(operation["changes"], timezone), "transactionId": transaction_id}
            created = await self._request(user, "POST", path, json=payload, headers=headers)
            return {"event_id": created.get("id"), "accepted": True}
        path += f"/{quote(operation['event_id'], safe='')}"
        if action in {"update", "reschedule"}:
            body = event_body(operation["changes"], timezone)
            if "description" in operation["changes"]:
                original = await self._request(user, "GET", path, params={"$select": "body,isOnlineMeeting"})
                if original.get("isOnlineMeeting"):
                    # Graph requires keeping the existing online-meeting blob when changing a body.
                    previous = original.get("body") or {}
                    content = previous.get("content", "")
                    if previous.get("contentType", "").lower() != "html":
                        content = escape(content)
                    body["body"] = {
                        "contentType": "HTML",
                        "content": escape(operation["changes"]["description"]) + "<hr>" + content,
                    }
            await self._request(user, "PATCH", path, json=body, headers=headers)
        else:
            endpoint = {
                "cancel": "cancel",
                "accept": "accept",
                "decline": "decline",
                "tentative": "tentativelyAccept",
                "propose_time": "tentativelyAccept",
            }[action]
            action_body: dict[str, Any] = {"comment": operation.get("comment", "")}
            if action != "cancel":
                action_body["sendResponse"] = True
            if action == "propose_time":
                action_body["proposedNewTime"] = operation["proposed_time"]
            await self._request(user, "POST", f"{path}/{endpoint}", json=action_body, headers=headers)
        return {"event_id": operation["event_id"], "accepted": True}

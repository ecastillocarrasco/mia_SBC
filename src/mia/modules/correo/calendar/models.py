"""Contrato independiente del proveedor; conserva referencias originales."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field, model_validator

from mia.auth import UserContext


class CalendarError(Exception):
    """Operación no disponible o no autorizada."""


class CalendarPerson(BaseModel):
    address: str
    name: str = ""
    kind: str = "required"
    response: str = "none"


class CalendarEvent(BaseModel):
    id: str
    provider: str = "microsoft365"
    calendar_id: str = "default"
    subject: str
    description: str = ""
    start: datetime
    end: datetime
    timezone: str
    organizer: CalendarPerson | None = None
    attendees: list[CalendarPerson] = Field(default_factory=list)
    location: str = ""
    online_url: str | None = None
    all_day: bool = False
    status: str = "confirmed"
    availability: str = "busy"
    recurrence: dict[str, Any] | None = None
    series_id: str | None = None
    occurrence_type: str = "singleInstance"
    response: str = "none"
    can_modify: bool = False
    can_respond: bool = False
    can_propose_time: bool = False
    version: str = ""


class CalendarInfo(BaseModel):
    id: str
    name: str
    can_edit: bool = False


class Recurrence(BaseModel):
    frequency: Literal["daily", "weekly", "monthly", "yearly"]
    interval: int = Field(default=1, ge=1, le=999)
    weekdays: list[Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]] = Field(
        default_factory=list
    )
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    month: int | None = Field(default=None, ge=1, le=12)
    start_date: date
    end_date: date | None = None
    count: int | None = Field(default=None, ge=1, le=999)

    @model_validator(mode="after")
    def validate_range(self) -> Recurrence:
        if self.end_date and self.count:
            raise ValueError("Indica fin por fecha o por número de ocurrencias, no ambos")
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("El final de la serie debe ser posterior al inicio")
        if self.frequency == "weekly" and not self.weekdays:
            raise ValueError("Indica los días de la semana")
        if self.frequency in {"monthly", "yearly"} and self.day_of_month is None:
            raise ValueError("Indica el día del mes")
        if self.frequency == "yearly" and self.month is None:
            raise ValueError("Indica el mes")
        return self


class EventInput(BaseModel):
    subject: str = Field(min_length=1, max_length=512)
    description: str = Field(default="", max_length=10000)
    start: datetime
    end: datetime
    timezone: str
    attendees: list[CalendarPerson] = Field(default_factory=list)
    location: str = Field(default="", max_length=512)
    online: bool = False
    all_day: bool = False
    recurrence: dict[str, Any] | None = None


Mutation = Literal["create", "update", "reschedule", "cancel", "accept", "decline", "tentative", "propose_time"]


class CalendarProvider(Protocol):
    name: str
    capabilities: frozenset[str]

    async def list_calendars(self, user: UserContext) -> list[CalendarInfo]: ...

    async def list_events(
        self, user: UserContext, start: datetime, end: datetime, timezone: str, calendar_id: str = "default"
    ) -> list[CalendarEvent]: ...

    async def get_event(
        self, user: UserContext, event_id: str, timezone: str, calendar_id: str = "default"
    ) -> CalendarEvent: ...

    async def get_availability(
        self, user: UserContext, addresses: list[str], start: datetime, end: datetime, timezone: str
    ) -> dict[str, Any]: ...

    async def mutate(self, user: UserContext, operation: dict[str, Any], transaction_id: str) -> dict[str, Any]: ...

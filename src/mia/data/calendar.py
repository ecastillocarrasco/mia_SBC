"""Propuestas y resultados de agenda; sin copia persistente del calendario."""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from mia.data.models import Base


class CalendarOperation(Base):
    __tablename__ = "calendar_operations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    session_key: Mapped[str] = mapped_column(String(32))
    provider: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    request_id: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column()
    result: Mapped[dict[str, Any]] = mapped_column(default=dict)

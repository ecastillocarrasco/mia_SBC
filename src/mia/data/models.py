"""Modelo de datos operativo.

El estado de la conversación vive solo en el servidor. El cliente envía
``session_id`` y el mensaje; nunca el contexto.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, ClassVar

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(UTC)


# JSONB en PostgreSQL (indexable); JSON genérico en SQLite para los tests.
JsonType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {dict[str, Any]: JsonType, list[Any]: JsonType}


class ConversationSession(Base):
    __tablename__ = "conversation_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    state: Mapped[dict[str, Any]] = mapped_column(default=dict)
    """Estado conversacional: foco (persona, departamento, periodo), último resultado, etc."""

    turns: Mapped[list[ConversationTurn]] = relationship(
        back_populates="session", order_by="ConversationTurn.created_at", cascade="all, delete-orphan"
    )


class ConversationTurn(Base):
    __tablename__ = "conversation_turns"
    __table_args__ = (Index("ix_conversation_turns_session_created", "session_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("conversation_sessions.id", ondelete="CASCADE"))
    request_id: Mapped[str | None] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(16))
    """``user`` o ``assistant``."""
    content: Mapped[str] = mapped_column(Text)
    speech: Mapped[str | None] = mapped_column(Text)
    avatar_state: Mapped[str | None] = mapped_column(String(32))
    tool_calls: Mapped[list[Any]] = mapped_column(default=list)
    presentation: Mapped[dict[str, Any]] = mapped_column(default=dict)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    session: Mapped[ConversationSession] = relationship(back_populates="turns")


class AuditEvent(Base):
    """Registro de accesos a datos (evidencia para ENS/RGPD)."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    request_id: Mapped[str | None] = mapped_column(String(64))
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    action: Mapped[str] = mapped_column(String(64))
    resource: Mapped[str] = mapped_column(String(128))
    outcome: Mapped[str] = mapped_column(String(32))
    detail: Mapped[dict[str, Any]] = mapped_column(default=dict)

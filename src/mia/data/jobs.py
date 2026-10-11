"""Trabajos en segundo plano (Bloque II, Fase G: Job Manager real).

Persistido en la base de datos real, nunca en memoria del proceso — un reinicio del servidor no debe
perder trabajos en curso ni su progreso. `params_json` es responsabilidad de quien encola el trabajo:
solo debe contener los parámetros de la operación (periodo, formato, filtros), nunca datos personales
ni cifras — el cálculo real se repite a partir de esos parámetros cuando el trabajo se ejecuta, igual
que cualquier otra herramienta de mIA.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from mia.data.models import Base, _now, _uuid

JOB_QUEUED = "queued"
JOB_RUNNING = "running"
JOB_VALIDATING = "validating"
JOB_COMPLETED = "completed"
JOB_FAILED = "failed"
JOB_CANCELLED = "cancelled"

JOB_STATES = (JOB_QUEUED, JOB_RUNNING, JOB_VALIDATING, JOB_COMPLETED, JOB_FAILED, JOB_CANCELLED)
JOB_TERMINAL_STATES = (JOB_COMPLETED, JOB_FAILED, JOB_CANCELLED)


class ReportJob(Base):
    __tablename__ = "report_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    kind: Mapped[str] = mapped_column(String(64))
    """Nombre de la operación a ejecutar (p. ej. "generar_informe_masivo")."""
    params_json: Mapped[str] = mapped_column(Text)
    """JSON de parámetros no personales (periodo, formato, filtros) — nunca nombres ni importes."""
    idempotency_key: Mapped[str | None] = mapped_column(String(128), index=True, unique=True)

    status: Mapped[str] = mapped_column(String(16), default=JOB_QUEUED, index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    progress_message: Mapped[str | None] = mapped_column(String(256))

    report_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("reports.id"))
    error_message: Mapped[str | None] = mapped_column(Text)

    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)

    lease_owner: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

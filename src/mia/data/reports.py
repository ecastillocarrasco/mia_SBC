"""Informes generados (PDF/Excel), accesibles solo para quien los pidió y durante un tiempo limitado."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from mia.data.models import Base, _now, _uuid


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(256))
    format: Mapped[str] = mapped_column(String(8))
    file_name: Mapped[str] = mapped_column(String(256))
    path: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    required_permission: Mapped[str | None] = mapped_column(String(64))
    """Valor de :class:`mia.auth.Permission` que el usuario debe conservar EN EL MOMENTO DE LA
    DESCARGA (no solo el de propiedad, que es lo único que comprobaba antes este modelo) para
    informes cuyo contenido es sensible (p. ej. ``"nominas:importes"``). ``None`` para el resto —
    mantiene el comportamiento de siempre (solo propiedad) para dominios no sensibles."""

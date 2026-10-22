"""Modelo canónico de Community, sincronizado desde SharePoint.

Las consultas de mIA leen de aquí (milisegundos), no de SharePoint — mismo criterio que
``mia.data.hr``.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from mia.data.models import Base


class NewsletterItem(Base):
    """Newsletter corporativa (lista «NewsletterCorporativa» del portal de SharePoint, RRHH)."""

    __tablename__ = "community_newsletter_items"

    sp_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    title: Mapped[str] = mapped_column(String(512))
    summary: Mapped[str | None] = mapped_column(Text)
    """«Resumen»: texto corto ya limpio, pensado para la tarjeta/teaser."""
    body: Mapped[str | None] = mapped_column(Text)
    """«Cuerpo»: texto plano (el HTML enriquecido original se convierte al sincronizar)."""
    category: Mapped[str | None] = mapped_column(String(128))
    featured: Mapped[bool] = mapped_column(Boolean, default=False)
    """«Destacada»."""
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    """«Activa»: si no lo está, nunca se muestra aunque no haya caducado."""
    order: Mapped[int | None] = mapped_column(Integer)
    """«Orden»: orden de publicación manual fijado por RRHH (no es una fecha)."""
    expires_at: Mapped[date | None] = mapped_column(Date)
    """«FechaCaducidad»: a partir de esta fecha se considera caducada aunque siga Activa."""
    image_url: Mapped[str | None] = mapped_column(String(1024))
    link_url: Mapped[str | None] = mapped_column(String(1024))
    button_text: Mapped[str | None] = mapped_column(String(128))
    """«TextoBoton»: rótulo que usa el portal para el enlace (p. ej. «Consultar», «Leer noticia»)."""
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

"""Descubrimiento de fuentes dinámicas: los calendarios Calendario<Departamento>_AAAA
no son una lista fija, así que hay que comprobar cuáles existen de verdad."""

from __future__ import annotations

import asyncio
from datetime import date

from mia.observability import get_logger
from mia.sources.definitions import (
    CALENDAR_BASE_YEAR,
    CALENDAR_DEPARTMENTS,
    SourceDefinition,
    calendar_source,
    calendar_title,
)
from mia.sources.sharepoint import SharePointClient

log = get_logger(__name__)


async def discover_calendar_sources(
    client: SharePointClient,
    *,
    departments: tuple[str, ...] = CALENDAR_DEPARTMENTS,
    base_year: int = CALENDAR_BASE_YEAR,
    upto_year: int | None = None,
) -> list[SourceDefinition]:
    """Comprueba qué listas Calendario<Departamento>[_AAAA] existen y devuelve sus fuentes.

    Cada comprobación es una petición ligera (columnas de la lista); un año/departamento
    sin calendario no es un error, solo no se sincroniza.
    """
    upto = upto_year or date.today().year
    candidates = [(dept, year) for dept in departments for year in range(base_year, upto + 1)]

    async def check(department: str, year: int) -> SourceDefinition | None:
        title = calendar_title(department, year)
        try:
            exists = await client.list_exists(title)
        except Exception as exc:  # un fallo de red no debe tirar el descubrimiento entero
            log.warning("calendar_discovery.failed", list_title=title, error=str(exc)[:200])
            return None
        return calendar_source(department, year) if exists else None

    results = await asyncio.gather(*(check(dept, year) for dept, year in candidates))
    found = [source for source in results if source is not None]
    log.info("calendar_discovery.finished", checked=len(candidates), found=len(found))
    return found

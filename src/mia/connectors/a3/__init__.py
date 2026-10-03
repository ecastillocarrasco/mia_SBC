"""Conectia (A3 de Wolters Kluwer): fichajes, sin implementar todavía.

RRHH se conectará con Conectia para leer fichajes (entrada/salida real, frente al turno
publicado que hoy viene de SharePoint). A fecha de esta reestructuración no hay documentación
de su API disponible, así que este módulo es solo la interfaz de enganche: cuando se conozca
el contrato real (REST, SOAP, fichero plano…), ``TimeClockConnector`` es el sitio donde
implementarlo, sin que el resto de mIA tenga que cambiar.

No importar este módulo desde ``modules/rrhh`` todavía: no hay implementación que registrar.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class ClockEvent:
    """Un fichaje real de una persona (entrada o salida), tal como lo reportará Conectia."""

    person_key: str
    """Mismo seudónimo de DNI/NIE que usa el resto de mIA (sources/ingestion lo calcula igual)."""
    at: datetime
    kind: str
    """«entrada» o «salida» (pendiente de confirmar el vocabulario exacto de la API de A3)."""


class TimeClockConnector(ABC):
    """Contrato mínimo para leer fichajes de Conectia. Sin implementación: falta documentación
    de su API (REST/SOAP/credenciales, paginación, zona horaria). Cuando se implemente, debe
    seudonimizar el identificador de persona igual que ``ingestion.pseudonym`` para poder
    cruzarlo con Empleados/Turnos sin introducir una segunda forma de identificar a alguien.
    """

    @abstractmethod
    async def fichajes(self, *, person_key: str, desde: date, hasta: date) -> list[ClockEvent]:
        """Fichajes reales de una persona en un rango de fechas."""
        raise NotImplementedError

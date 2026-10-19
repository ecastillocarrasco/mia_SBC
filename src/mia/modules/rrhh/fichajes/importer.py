"""Importación manual del Excel de fichajes de Conectia (A3 Wolters Kluwer) — solo entornos de
prueba (ver docstring de ``Permission.FICHAJES_LEER``); cuando exista la API real de Conectia,
``mia.connectors.a3.TimeClockConnector`` es el sitio para implementarla, nunca este importador.

Formato real confirmado contra las exportaciones de la semana 41 (PISOS/RESTAURANTE, 2026-10-19):
una fila por marca SUELTA (no por día), columnas "Fecha" (datetime completo con segundos, no solo
fecha — "Hora marcaje" es una versión truncada redundante, se ignora), "Código del empleado",
"Nombre completo" (formato "Apellido1 [Apellido2], Nombre"), "Origen del marcaje", "Motivo",
"Nombre Terminal", "Tipo marcaje" (Reloj/App/App offline), "Link localización".

Identificación de persona: el "Código del empleado" de Conectia NO coincide con
``Employee.employee_code`` (formatos distintos, confirmado contra datos reales). Se cruza por
NOMBRE COMPLETO como CONJUNTO de palabras — nunca por orden ni por fragmento ("de la rosa" aparece
en dos empleados distintos; comparar solo ese fragmento sería ambiguo) — contra
``Employee.name_key``, que ya normaliza tildes/ñ/mayúsculas (``mia.text.normalize_key``).

Tres niveles de cruce, en este orden, nunca un fragmento ni una comparación difusa genérica:
  1. Coincidencia EXACTA de conjunto de palabras (tras aplicar ``_FULL_NAME_CORRECTIONS`` —
     variantes ortográficas puntuales entre Conectia y mIA, confirmadas una a una por el usuario
     contra datos reales, siempre por NOMBRE COMPLETO: una regla genérica por palabra suelta,
     p. ej. "vanesa"->"vanessa" para cualquier aparición, corregía por error a una persona
     DISTINTA que sí se llama así de verdad — confirmado contra datos reales).
  2. Si no hay exacta: el nombre de ``Employee`` (más corto a veces — la maestra de mIA puede
     omitir un segundo nombre que Conectia sí trae, confirmado contra datos reales: "Melania
     Rosello Diaz" en mIA frente a "MELANIA JACINTA ROSELLO DIAZ" en Conectia) es un SUBCONJUNTO
     de las palabras de Conectia. Se acepta solo si es el ÚNICO empleado para el que esto ocurre;
     si hay más de uno, es ambiguo y se reporta, nunca se adivina cuál es.

Una fila sin cruce único (0 o >1 coincidencias) se reporta, nunca se adivina ni se descarta en
silencio.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mia.data import ClockMark, Database, Employee
from mia.text import normalize_key

SOURCE = "excel_conectia"

_EXPECTED_COLUMNS = (
    "Fecha",
    "Código del empleado",
    "Nombre completo",
    "Origen del marcaje",
    "Nombre Terminal",
    "Tipo marcaje",
)


@dataclass(slots=True)
class ImportReport:
    files: int = 0
    rows_read: int = 0
    imported: int = 0
    unmatched: dict[str, int] = field(default_factory=dict)
    """Nombre crudo de Conectia -> nº de filas sin ninguna persona que coincida."""
    ambiguous: dict[str, int] = field(default_factory=dict)
    """Nombre crudo de Conectia -> nº de filas con MÁS DE UNA persona que coincide (no debería
    pasar con 0 nombres duplicados en la plantilla, pero se reporta igual, nunca se adivina)."""
    period: tuple[datetime, datetime] | None = None

    @property
    def unmatched_rows(self) -> int:
        return sum(self.unmatched.values())

    @property
    def ambiguous_rows(self) -> int:
        return sum(self.ambiguous.values())


_FULL_NAME_CORRECTIONS: dict[str, str] = {
    "jenifer jimenez jimenez": "jennifer jimenez jimenez",
    "jenifer porcel sanchez": "jennifer porcel sanchez",
    "vanesa sanchez valle": "vanessa sanchez valle",
    "cristiane de conceicao de lima": "cristiane da conceicao de lima",
}
"""Variantes ortográficas puntuales entre Conectia y la ficha de mIA, confirmadas una a una por el
usuario contra la importación real (semana 41) — SIEMPRE el NOMBRE COMPLETO, nunca una palabra
suelta: una corrección genérica por palabra (p. ej. "vanesa"->"vanessa" para cualquier aparición)
rompía a una persona DISTINTA que sí se llama "Vanesa" de verdad (confirmado contra datos reales:
corregía por error a "Yesica Vanesa Jofre", que no tiene nada que ver con "Vanessa Sanchez
Valle") — el mismo motivo por el que no existe una regla genérica "de"->"da".

"Gabriel Felippe Glibert" (sospechado inicialmente como error ortográfico) NO necesitó ninguna
corrección: la maestra de empleados (SharePoint) simplemente llevaba 17 días sin sincronizar y no
lo tenía todavía — tras refrescar el sync de "empleados" cruza exacto, con la misma grafía que
Conectia. No añadir aquí una corrección "glibert"->"gilbert": sería incorrecta y rompería el
cruce real."""


def _name_tokens(raw: str) -> frozenset[str]:
    """"Apellido1 [Apellido2], Nombre" -> conjunto de palabras normalizado, sin importar el orden
    ("Rosello Diaz, Melania" y "Melania Rosello Diaz" producen el mismo conjunto), con las
    variantes ortográficas conocidas ya corregidas (siempre por nombre completo, ver arriba)."""
    surnames, _, first_name = raw.partition(",")
    normalized = normalize_key(f"{first_name} {surnames}")
    normalized = _FULL_NAME_CORRECTIONS.get(normalized, normalized)
    return frozenset(normalized.split())


@dataclass(slots=True)
class _EmployeeIndex:
    by_tokens: dict[frozenset[str], list[Employee]]
    all_with_name: list[tuple[frozenset[str], Employee]]

    def match(self, tokens: frozenset[str]) -> list[Employee]:
        exact = self.by_tokens.get(tokens)
        if exact:
            return exact
        # El nombre del empleado puede ser más corto que el de Conectia (le falta un segundo
        # nombre) — se acepta como subconjunto SOLO si es el único candidato así.
        return [e for e_tokens, e in self.all_with_name if e_tokens and e_tokens <= tokens]


async def _employee_index(db: AsyncSession) -> _EmployeeIndex:
    employees = list((await db.scalars(select(Employee))).all())
    by_tokens: dict[frozenset[str], list[Employee]] = defaultdict(list)
    all_with_name: list[tuple[frozenset[str], Employee]] = []
    for e in employees:
        if e.name_key:
            tokens = frozenset(e.name_key.split())
            by_tokens[tokens].append(e)
            all_with_name.append((tokens, e))
    return _EmployeeIndex(by_tokens, all_with_name)


def _read_rows(path: Path) -> list[dict[str, Any]]:
    wb = load_workbook(path, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    header = [str(c).strip() if c is not None else "" for c in rows[0]]
    missing = [c for c in _EXPECTED_COLUMNS if c not in header]
    if missing:
        raise ValueError(
            f"{path.name}: faltan columnas esperadas {missing} en la cabecera real {header} "
            "— no se importa nada de este fichero, no se adivina el formato."
        )
    idx = {name: header.index(name) for name in header if name}
    out: list[dict[str, Any]] = []
    for row in rows[1:]:
        if row[idx["Fecha"]] is None or row[idx["Nombre completo"]] is None:
            continue
        out.append({name: row[i] for name, i in idx.items()})
    return out


async def import_directory(
    db: Database, directory: Path, *, timezone: str = "Europe/Madrid", now: datetime
) -> ImportReport:
    """Importa TODOS los .xlsx de ``directory`` (un fichero por departamento/semana en los
    ficheros reales) — upsert idempotente por ``(person_key, at)``: reimportar el mismo fichero no
    duplica, solo actualiza metadatos (origen, terminal) si han cambiado."""
    tz = ZoneInfo(timezone)
    report = ImportReport()
    paths = sorted(directory.glob("*.xlsx"))
    async with db.session() as session:
        index = await _employee_index(session)
        for path in paths:
            report.files += 1
            rows = _read_rows(path)
            for row in rows:
                report.rows_read += 1
                raw_name = str(row["Nombre completo"])
                matches = [e for e in index.match(_name_tokens(raw_name)) if e.person_key]
                if not matches:
                    report.unmatched[raw_name] = report.unmatched.get(raw_name, 0) + 1
                    continue
                if len(matches) > 1:
                    report.ambiguous[raw_name] = report.ambiguous.get(raw_name, 0) + 1
                    continue
                at: datetime = row["Fecha"]
                if at.tzinfo is None:
                    at = at.replace(tzinfo=tz)
                await session.merge(
                    ClockMark(
                        person_key=matches[0].person_key,
                        at=at,
                        origin=row.get("Origen del marcaje") or None,
                        device_type=row.get("Tipo marcaje") or None,
                        terminal_name=row.get("Nombre Terminal") or None,
                        source=SOURCE,
                        imported_at=now,
                    )
                )
                report.imported += 1
                lo, hi = report.period or (at, at)
                report.period = (min(lo, at), max(hi, at))
    return report

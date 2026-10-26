"""Piezas compartidas por los dominios de RRHH: personas, periodos, frescura y presentación."""

from __future__ import annotations

import difflib
import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from mia.conversation import ToolResult, ToolStatus
from mia.core.i18n import t
from mia.data import Database, Employee, ShiftDay, Vacation
from mia.data.sources import STALE_AFTER, freshness
from mia.ingestion.mappers.hr import ShiftKind
from mia.text import normalize_key

MAX_ROWS_FOR_MODEL = 40
"""Filas que ve el modelo; la interfaz recibe la lista completa."""


@dataclass(frozen=True, slots=True)
class Deps:
    db: Database
    stale_after: timedelta = STALE_AFTER
    llm: Any = None
    """Proveedor LLM (para embeddings de la búsqueda de CVs)."""
    settings: Any = None
    """Settings de la aplicación (correo, informes, currículums)."""
    graph: Any = None
    """Cliente de Microsoft Graph (correo), si está configurado."""
    sharepoint: Any = None
    """Cliente de SharePoint (RRHH) para leer documentos en el momento, si está configurado."""
    services: dict[str, Any] = field(default_factory=dict)
    """Servicios compartidos por varias herramientas de un dominio (índice de CVs, almacén de informes)."""

    async def freshness(self, db: AsyncSession, *sources: str) -> dict[str, Any]:
        return await freshness(db, *sources, stale_after=self.stale_after)


# ------------------------------------------------------------------ parámetros comunes
class PersonaParams(BaseModel):
    empleado_id: int | None = Field(default=None, description="ID de la persona (del foco o de una búsqueda previa)")
    nombre: str | None = Field(
        default=None,
        description=(
            "Nombre o parte del nombre que ha escrito la persona en ESTE turno. OBLIGATORIO "
            "cuando el turno nombra a alguien, aunque también se mande empleado_id del foco — "
            "es la única forma de detectar un foco obsoleto (otra persona). Déjalo vacío solo en "
            "preguntas de seguimiento que no nombran a nadie (\"muéstrame sus turnos\")."
        ),
    )

    @model_validator(mode="after")
    def _one_of(self) -> PersonaParams:
        if self.empleado_id is None and not (self.nombre or "").strip():
            raise ValueError("Indica empleado_id o nombre")
        return self


class Periodo(BaseModel):
    desde: date | None = Field(default=None, description="Fecha inicial AAAA-MM-DD (por defecto hoy)")
    hasta: date | None = Field(default=None, description="Fecha final AAAA-MM-DD (por defecto igual a desde)")

    def resolve(self, today: date, default_days: int = 0) -> tuple[date, date]:
        start = self.desde or today
        end = self.hasta or (start + timedelta(days=default_days))
        if end < start:
            start, end = end, start
        return start, min(end, start + timedelta(days=366))


# ------------------------------------------------------------------ personas
@dataclass(frozen=True, slots=True)
class PersonMatch:
    status: ToolStatus
    employee: Employee | None = None
    candidates: tuple[Employee, ...] = ()
    suggestions: tuple[str, ...] = ()


def person_summary(e: Employee) -> dict[str, Any]:
    return {
        "empleado_id": e.sp_id,
        "nombre": e.name,
        "departamento": e.department,
        "puesto": e.position,
        "activo": e.active,
    }


def focus_person(e: Employee) -> dict[str, Any]:
    return {"foco_persona": {"empleado_id": e.sp_id, "nombre": e.name, "departamento": e.department}}


async def find_people(db: AsyncSession, query: str, *, include_inactive: bool = True) -> list[Employee]:
    """Coincidencia por palabras: todas las del texto deben aparecer en el nombre (sin tildes)."""
    tokens = [t for t in normalize_key(query).split() if len(t) > 1]
    if not tokens:
        return []
    stmt = select(Employee)
    for token in tokens:
        stmt = stmt.where(or_(Employee.name_key.like(f"{token}%"), Employee.name_key.like(f"% {token}%")))
    if not include_inactive:
        stmt = stmt.where(Employee.active.is_(True))
    return list((await db.scalars(stmt.order_by(Employee.active.desc(), Employee.name))).all())


async def _without_one_word(db: AsyncSession, query: str) -> PersonMatch | None:
    """Una palabra de más o mal escrita («testaltaturno test2» para «testAltaTurno»): se prueba sin cada una."""
    tokens = normalize_key(query).split()
    if len(tokens) < 2:
        return None
    loose = {
        e.sp_id: e for i in range(len(tokens)) for e in await find_people(db, " ".join(tokens[:i] + tokens[i + 1 :]))
    }
    if len(loose) == 1:
        return PersonMatch(ToolStatus.OK, next(iter(loose.values())))
    return PersonMatch(ToolStatus.AMBIGUOUS, candidates=tuple(list(loose.values())[:10])) if loose else None


def _name_matches(query: str, name_key: str) -> bool:
    """Mismo criterio que ``find_people``: todas las palabras de ``query`` deben aparecer en
    el nombre, para decidir si un ``nombre`` dado junto a un ``empleado_id`` de foco realmente
    se refiere a esa misma persona (y no a otra, por un foco obsoleto)."""
    tokens = [t for t in normalize_key(query).split() if len(t) > 1]
    return bool(tokens) and all(token in name_key for token in tokens)


_FICHA_FILLER_WORDS = frozenset({
    "ficha", "completa", "completo", "muestrame", "muestrales", "enseñame", "ensename",
    "quiero", "ver", "dame", "pasame", "la", "el", "de", "del", "sus", "su", "por", "favor",
    "resumen", "detalle", "detallada", "detallado", "informacion", "datos", "perfil",
})

# Subconjunto de arriba SIN "la"/"el"/"de"/"del"/"sus"/"su"/"por"/"favor": esas sí pueden ser
# parte real de un apellido español ("de la Cruz", "del Pozo") y nunca deben quitarse de un
# `nombre` explícito, solo de la extracción heurística del mensaje completo de abajo.
_FICHA_LEADING_COMMAND_WORDS = frozenset({
    "ficha", "completa", "completo", "muestrame", "muestrales", "enseñame", "ensename",
    "quiero", "ver", "dame", "pasame", "resumen", "detalle", "detallada", "detallado",
    "informacion", "datos", "perfil",
})


def _strip_leading_command_words(nombre: str) -> str:
    """El modelo a veces incluye la propia palabra de mando al principio del argumento `nombre`
    en vez de solo el nombre (reproducido en preprod 2026-10-25: nombre="ficha mari camen
    garcia") -- como la búsqueda exige que TODAS las palabras de `nombre` encajen en el nombre
    real, una sola palabra de mando de más tira abajo toda la búsqueda. Solo se quitan por
    delante, nunca en medio de la frase."""
    words = nombre.split()
    while words and normalize_key(words[0]) in _FICHA_LEADING_COMMAND_WORDS:
        words.pop(0)
    return " ".join(words) if words else nombre


def _fallback_name_from_message(user_message: str) -> str:
    """Si el modelo manda ``empleado_id`` sin ``nombre`` (lo normal cuando la pregunta sigue el
    foco: "muéstrame sus vacaciones"), este es el único dato adicional disponible para detectar
    un foco obsoleto -- el propio texto que escribió la persona en este turno. Quita las palabras
    de relleno más comunes de "ficha de empleado" para quedarse solo con lo que podría ser un
    nombre; una pregunta de seguimiento normal sin nombre alguno queda vacía tras este filtro."""
    tokens = [t for t in normalize_key(user_message).split() if len(t) > 1 and t not in _FICHA_FILLER_WORDS]
    return " ".join(tokens)


async def resolve_person(db: AsyncSession, params: PersonaParams, *, ctx: Any = None) -> PersonMatch:
    query = _strip_leading_command_words(params.nombre) if params.nombre else ""
    if params.empleado_id is not None:
        employee = await db.get(Employee, params.empleado_id)
        # Defensa en profundidad: el modelo puede mandar un empleado_id obsoleto (de un foco de
        # turnos atrás) o directamente inventado (ninguno de los dos existe de verdad, no solo el
        # "obsoleto" apunta a otra persona) — ambos casos reproducidos de verdad en preprod, el
        # segundo con el nombre correcto SIN rellenar el argumento `nombre`, solo en el mensaje
        # del turno. Nunca confiar en el id a ciegas.
        if query.strip():
            # Nombre explícito en los argumentos junto al id.
            if employee is not None and _name_matches(query, employee.name_key):
                return PersonMatch(ToolStatus.OK, employee)
            # No existe, o existe pero no coincide -> cae a la búsqueda por nombre de abajo,
            # ignorando el empleado_id obsoleto/erróneo.
        else:
            # Sin nombre explícito en los argumentos: el caso normal es una pregunta de
            # seguimiento que confía en el foco ("muéstrame sus turnos") y aquí NO hay que tocar
            # nada. El único dato adicional disponible para detectar un id obsoleto/inventado es
            # el propio mensaje del turno — si nombra de verdad a otra persona que existe en la
            # base de datos, eso manda por encima del id (exista o no); si no nombra a nadie (o
            # solo palabras sueltas que no son un nombre real), el id sigue mandando si existe.
            fallback = _fallback_name_from_message(getattr(ctx, "user_message", "") or "") if ctx is not None else ""
            if fallback and not (employee is not None and _name_matches(fallback, employee.name_key)):
                fallback_matches = await find_people(db, fallback)
                if fallback_matches:
                    query = fallback
                elif employee is not None:
                    return PersonMatch(ToolStatus.OK, employee)
                else:
                    return PersonMatch(ToolStatus.NOT_FOUND)
            elif employee is not None:
                return PersonMatch(ToolStatus.OK, employee)
            else:
                return PersonMatch(ToolStatus.NOT_FOUND)
    matches = await find_people(db, query)
    active = [m for m in matches if m.active]
    pool = active or matches
    if len(pool) == 1:
        return PersonMatch(ToolStatus.OK, pool[0])
    if len(pool) > 1:
        exact = [m for m in pool if m.name_key == normalize_key(query)]
        if len(exact) == 1:
            return PersonMatch(ToolStatus.OK, exact[0])
        # Defensa en profundidad adicional, reproducida en preprod 2026-10-26: el modelo a veces
        # recorta un apellido real al construir `nombre` (p. ej. nombre="mari carmen" para la
        # pregunta "ficha mari carmen salas") -- el texto completo del turno SÍ tenía el apellido
        # que habría desambiguado. Antes de preguntar, probar con ese texto completo (limpio de
        # palabras de mando); si estrecha a una única persona real, usarla. Si no estrecha nada
        # (p. ej. un typo real, "camen" por "carmen", sin palabras nuevas que aportar), se sigue
        # preguntando como antes -- nunca se adivina.
        if ctx is not None:
            richer = _fallback_name_from_message(getattr(ctx, "user_message", "") or "")
            if richer and richer != normalize_key(query):
                richer_matches = await find_people(db, richer)
                richer_active = [m for m in richer_matches if m.active]
                richer_pool = richer_active or richer_matches
                if len(richer_pool) == 1:
                    return PersonMatch(ToolStatus.OK, richer_pool[0])
        return PersonMatch(ToolStatus.AMBIGUOUS, candidates=tuple(pool[:10]))
    if loose := await _without_one_word(db, query):
        return loose
    names = (await db.scalars(select(Employee.name))).all()
    by_key = {normalize_key(n): n for n in names}
    close = difflib.get_close_matches(normalize_key(query), list(by_key), n=3, cutoff=0.75)
    return PersonMatch(ToolStatus.NOT_FOUND, suggestions=tuple(by_key[c] for c in close))


def person_problem(match: PersonMatch, query: str | None) -> ToolResult:
    """Resultado para el modelo cuando la persona no se ha podido fijar."""
    if match.status is ToolStatus.AMBIGUOUS:
        return ToolResult(
            ToolStatus.AMBIGUOUS,
            {
                "mensaje": "Hay varias personas que encajan: pregunta cuál antes de continuar.",
                "candidatos": [person_summary(c) for c in match.candidates],
            },
            table(
                "Personas que encajan",
                ["Nombre", "Departamento", "Puesto", "Activo"],
                [[c.name, c.department, c.position, "Sí" if c.active else "No"] for c in match.candidates],
            ),
        )
    summary: dict[str, Any] = {"mensaje": f"No hay ninguna persona que encaje con «{query}»."}
    if match.suggestions:
        summary["quizas_quiso_decir"] = list(match.suggestions)
    return ToolResult(ToolStatus.NOT_FOUND, summary)


# ------------------------------------------------------------------ presentación
def table(title: str, columns: list[str], rows: list[list[Any]], **extra: Any) -> dict[str, Any]:
    return {"type": "table", "title": title, "columns": columns, "rows": rows, **extra}


def fmt_date(value: date | None) -> str | None:
    return value.strftime("%d/%m/%Y") if value else None


def days_between(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def merge_periods(days: list[date]) -> list[tuple[date, date]]:
    """Agrupa días consecutivos en periodos: [1,2,3,5] → [(1,3), (5,5)]."""
    periods: list[tuple[date, date]] = []
    for day in sorted(set(days)):
        if periods and day - periods[-1][1] == timedelta(days=1):
            periods[-1] = (periods[-1][0], day)
        else:
            periods.append((day, day))
    return periods


# ------------------------------------------------------------------ departamentos
@dataclass(frozen=True, slots=True)
class DepartmentMatch:
    status: ToolStatus
    name: str | None = None
    key: str | None = None
    options: tuple[str, ...] = ()


async def resolve_department(db: AsyncSession, query: str | None) -> DepartmentMatch:
    """Localiza un departamento por nombre aproximado ("pisos" → "Pisos")."""
    if not (query or "").strip():
        return DepartmentMatch(ToolStatus.OK)
    rows = (await db.execute(select(Employee.department, Employee.department_key).distinct())).all()
    known: dict[str, str] = {key: name for name, key in rows if key and name}
    wanted = normalize_key(query)
    if wanted in known:
        return DepartmentMatch(ToolStatus.OK, known[wanted], wanted)
    partial = [k for k in known if wanted in k or k in wanted]
    if len(partial) == 1:
        return DepartmentMatch(ToolStatus.OK, known[partial[0]], partial[0])
    options = tuple(sorted(known[k] for k in (partial or known)))
    status = ToolStatus.AMBIGUOUS if partial else ToolStatus.NOT_FOUND
    return DepartmentMatch(status, options=options)


def department_problem(match: DepartmentMatch, query: str | None) -> ToolResult:
    verb = (
        "Hay varios departamentos que encajan" if match.status is ToolStatus.AMBIGUOUS else "No existe ese departamento"
    )
    return ToolResult(match.status, {"mensaje": f"{verb} («{query}»).", "departamentos": list(match.options)})


# ------------------------------------------------------------------ cohortes (CTX-002)
POPULATION = "ultima_poblacion"
MAX_POPULATION = 2000


class CohortParams(BaseModel):
    sobre_resultado_anterior: bool = Field(
        default=False,
        description="true si el usuario se refiere al resultado anterior («de esos», «de ellas»)",
    )
    resultado: str | None = Field(
        default=None,
        description="Con «volviendo a…» o si se refiere a un grupo que NO es el último: parte de la etiqueta de "
        "ese resultado anterior (p. ej. «baja», «reincorporaciones»). Implica sobre_resultado_anterior.",
    )


class ActivosParams(BaseModel):
    incluir_inactivos: bool = Field(
        default=False,
        description="POB-001: por defecto SOLO la plantilla activa. true únicamente si el usuario pide "
        "expresamente inactivos, antiguos empleados o «todos, activos e inactivos».",
    )


POBLACION_ACTIVA = "plantilla activa (POB-001)"


def active_person_keys() -> Any:
    """Subconsulta con los seudónimos de DNI de la plantilla activa."""
    return select(Employee.person_key).where(Employee.active.is_(True), Employee.person_key.is_not(None))


def active_emails() -> Any:
    """Subconsulta con los emails (en minúsculas) de la plantilla activa."""
    return select(func.lower(Employee.email)).where(Employee.active.is_(True), Employee.email.is_not(None))


def population_label(include_inactive: bool) -> str:
    return "activos e inactivos" if include_inactive else POBLACION_ACTIVA


def population_state(label: str, employees: list[Employee]) -> dict[str, Any]:
    """Conserva en privado la población de una respuesta para poder cruzarla después."""
    people = employees[:MAX_POPULATION]
    return {
        POPULATION: {
            "etiqueta": label,
            "total": len(employees),
            "empleado_ids": [e.sp_id for e in people],
            "person_keys": [e.person_key for e in people if e.person_key],
            "emails": [e.email for e in people if e.email],
        }
    }


def previous_population(ctx: Any, label: str | None = None) -> dict[str, Any] | None:
    """El último resultado con personas o, si se indica una etiqueta, el más reciente que la contiene."""
    label = label or referred_label(getattr(ctx, "user_message", ""))
    if label:
        wanted = normalize_key(label)
        for population in reversed(ctx.session_state.get("historial_poblaciones") or []):
            if isinstance(population, dict) and wanted in normalize_key(population.get("etiqueta")):
                return population
    value = ctx.session_state.get(POPULATION)
    return value if isinstance(value, dict) else None


def no_population() -> ToolResult:
    return ToolResult(ToolStatus.NOT_FOUND, t("errors.no_previous_population"))


async def employees_for(
    db: AsyncSession, *, person_keys: set[str] | None = None, emails: set[str] | None = None
) -> list[Employee]:
    """Empleados a partir de seudónimos o emails (para convertir un resultado en población)."""
    conditions = []
    if person_keys:
        conditions.append(Employee.person_key.in_(person_keys))
    if emails:
        conditions.append(Employee.email.in_(emails))
    if not conditions:
        return []
    return list((await db.scalars(select(Employee).where(or_(*conditions)).order_by(Employee.name))).all())


# ------------------------------------------------------------------ cruce con EmpleadosCorporativos
@dataclass(frozen=True, slots=True)
class PersonInfo:
    empleado_id: int
    puesto: str | None
    departamento: str | None
    activo: bool
    responsable: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "empleado_id": self.empleado_id,
            "puesto": self.puesto,
            "departamento_actual": self.departamento,
            "activo": self.activo,
            "responsable": self.responsable,
        }


class PeopleDirectory:
    """Cruza cualquier listado con la ficha del empleado (EmpleadosCorporativos) por email o por
    seudónimo del DNI, para que vacaciones, turnos, saldos… lleven también puesto, departamento actual,
    responsable y si sigue activo (como hacía el sistema anterior)."""

    def __init__(self, employees: list[Employee]) -> None:
        self._by_email: dict[str, PersonInfo] = {}
        self._by_key: dict[str, PersonInfo] = {}
        for e in sorted(employees, key=lambda x: x.active):  # los activos prevalecen si hay duplicados
            info = PersonInfo(e.sp_id, e.position, e.department, bool(e.active), e.manager_name)
            if e.email:
                self._by_email[e.email.lower()] = info
            if e.person_key:
                self._by_key[e.person_key] = info

    @classmethod
    async def load(
        cls, db: AsyncSession, *, emails: set[str] | None = None, person_keys: set[str] | None = None
    ) -> PeopleDirectory:
        conditions = []
        if emails:
            conditions.append(func.lower(Employee.email).in_({e.lower() for e in emails if e}))
        if person_keys:
            conditions.append(Employee.person_key.in_({k for k in person_keys if k}))
        if not conditions:
            return cls([])
        return cls(list((await db.scalars(select(Employee).where(or_(*conditions)))).all()))

    def get(self, *, email: str | None = None, person_key: str | None = None) -> PersonInfo | None:
        return (self._by_email.get(email.lower()) if email else None) or (
            self._by_key.get(person_key) if person_key else None
        )

    def puesto(self, *, email: str | None = None, person_key: str | None = None) -> str | None:
        info = self.get(email=email, person_key=person_key)
        return info.puesto if info else None


def document_entry(
    kind: str, item_id: int, title: str, *, subtitle: str | None = None, date: str | None = None
) -> dict[str, Any]:
    """Un documento que la pantalla puede abrir (/api/documents/{cv|nomina|documento}/{id}, con permiso y auditoría)."""
    return {
        "kind": kind,
        "title": title,
        "subtitle": subtitle,
        "date": date,
        "url": f"/api/documents/{kind}/{item_id}",
    }


CONFIRMED_VACATION_STATES = frozenset({"aceptada", "aprobada"})
PENDING_SIGNATURE_STATE = "pendiente firma"


async def _vacation_shift_days(db: AsyncSession, emails: set[str]) -> dict[str, list[date]]:
    """Días con turno de tipo Vacaciones ya publicado, por email (orden ascendente)."""
    if not emails:
        return {}
    out: dict[str, list[date]] = defaultdict(list)
    rows = await db.execute(
        select(ShiftDay.email, ShiftDay.day)
        .where(ShiftDay.email.in_(emails), ShiftDay.kind == ShiftKind.VACACIONES)
        .order_by(ShiftDay.email, ShiftDay.day)
    )
    for email, day in rows:
        if email:
            out[email].append(day)
    return out


async def confirmed_vacations(db: AsyncSession, rows: Sequence[Vacation]) -> list[Vacation]:
    """Solicitudes de vacaciones/asuntos propios que cuentan como «en firme».

    Aceptada y aprobada siempre cuentan. Pendiente de firma solo cuenta cuando el turno YA
    refleja Vacaciones en el periodo exacto de esa solicitud (VAC-002, REI-001): se da por
    hecho que las vacaciones se firman y se aceptan, pero a veces la firma llega después de
    disfrutarlas; si solo hay solicitud y ningún turno de Vacaciones en esas fechas, la
    solicitud todavía no cuenta.
    """
    pending_emails = {
        v.employee_email
        for v in rows
        if v.employee_email and v.start_date and v.end_date and normalize_key(v.status) == PENDING_SIGNATURE_STATE
    }
    shift_days = await _vacation_shift_days(db, pending_emails)

    def _counts(v: Vacation) -> bool:
        status = normalize_key(v.status)
        if status in CONFIRMED_VACATION_STATES:
            return True
        if status != PENDING_SIGNATURE_STATE or not v.employee_email or not v.start_date or not v.end_date:
            return False
        return any(v.start_date <= d <= v.end_date for d in shift_days.get(v.employee_email, []))

    return [v for v in rows if _counts(v)]


_REFERRED = re.compile(
    r"\bvolviendo\s+a\s+(?:los|las|el|la)\s+(?:\w+\s+){0,3}?(?:de|que\s+(?:estaban|eran|est[aá]n)\s+de)\s+(\w+)",
    re.IGNORECASE,
)


def referred_label(message: str | None) -> str | None:
    """«Volviendo a los de baja…» → «baja»: el grupo anterior al que se refiere el usuario."""
    match = _REFERRED.search(message or "")
    return match.group(1) if match else None


_GENERIC_FOLLOWUP = re.compile(
    r"^\s*[¿]?\s*(?:y\s+)?"
    r"(?:qui[eé]nes?|cu[aá]les?|cu[aá]nt[oa]s?)\s+"
    r"(?:personas?\s+)?(?:distintas?\s+)?"
    r"(?:son|hay|eran|quedan|representan)"
    r"(?:\s+(?:esas?|esos?|ellas?|ellos?|en\s+total)(?:\s+personas?)?)?"
    r"\s*[.?!¿]*\s*$",
    re.IGNORECASE,
)
"""«Quiénes son», «cuántos son», «cuántas personas distintas representan»…: un seguimiento sin
criterio propio, sin «de esos/ellas» explícito. El modelo debería marcar sobre_resultado_anterior
él solo (se le indica en el prompt), pero en la práctica no siempre lo hace con esta formulación
(el prompt solo cita «de esos/ellas» como ejemplo) — de ahí este respaldo determinista."""


def wants_previous(p: Any, ctx: Any) -> bool:
    """¿La consulta es sobre un resultado anterior? Lo dice el modelo, lo delata «volviendo a los
    de…», o es un seguimiento genérico sin criterio propio («quiénes son», «cuántos son»)."""
    message = getattr(ctx, "user_message", "") or ""
    return bool(
        getattr(p, "sobre_resultado_anterior", False)
        or getattr(p, "resultado", None)
        or referred_label(message)
        or _GENERIC_FOLLOWUP.search(message)
    )

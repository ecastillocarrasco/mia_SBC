"""SemanticFieldRegistry — sinónimos en lenguaje natural → campo interno.

Permite que el usuario diga «fecha de entrada» y el sistema sepa que
es ``hire_date``, o «cuánto cobra» y sepa que es ``liquido``.

Cada FieldDef describe:
  - el campo físico/lógico en el sistema
  - sinónimos reconocidos (normalizados sin tildes)
  - dominio al que pertenece
  - tipo de dato
  - operaciones de agregación válidas
  - permiso necesario para verlo (None = público)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from mia.text import normalize_key

Domain = Literal[
    "employee", "shift", "vacation", "payroll", "document",
    "timesheet", "candidate", "report", "system",
]

AggOp = Literal[
    "count", "sum", "mean", "median", "min", "max",
    "percentile", "stddev", "trend", "distribution",
]

FieldType = Literal["string", "int", "float", "date", "bool", "enum"]


@dataclass(frozen=True, slots=True)
class FieldDef:
    name: str
    """Nombre interno / clave canónica."""
    domain: Domain
    type: FieldType
    synonyms: tuple[str, ...]
    """Sinónimos ya normalizados (sin tildes, minúsculas)."""
    agg_ops: tuple[AggOp, ...]
    description: str = ""
    permission: str | None = None
    """Permiso de mia.auth.Permission (str) necesario para ver este campo."""
    unit: str | None = None


class SemanticFieldRegistry:
    """Registro de campos por sinónimo.

    Uso::

        reg = SemanticFieldRegistry()
        reg.add(FieldDef("age", "employee", "int", ("edad", "anos", "age"), ...))
        field = reg.resolve("cuántos años tiene")  # → FieldDef(name="age")
    """

    def __init__(self) -> None:
        self._by_synonym: dict[str, FieldDef] = {}
        self._by_name: dict[str, FieldDef] = {}

    def add(self, fd: FieldDef) -> None:
        self._by_name[fd.name] = fd
        for syn in fd.synonyms:
            key = normalize_key(syn)
            self._by_synonym[key] = fd

    def resolve(self, text: str) -> FieldDef | None:
        """Devuelve el FieldDef cuyo sinónimo está contenido en *text*, o None."""
        norm = normalize_key(text)
        # exact match first
        if norm in self._by_synonym:
            return self._by_synonym[norm]
        # substring match (longest wins)
        matches = [(syn, fd) for syn, fd in self._by_synonym.items() if syn in norm]
        if matches:
            return max(matches, key=lambda x: len(x[0]))[1]
        return None

    def by_name(self, name: str) -> FieldDef | None:
        return self._by_name.get(name)

    def by_domain(self, domain: Domain) -> list[FieldDef]:
        seen: set[str] = set()
        result = []
        for fd in self._by_name.values():
            if fd.domain == domain and fd.name not in seen:
                seen.add(fd.name)
                result.append(fd)
        return result

    def all_fields(self) -> list[FieldDef]:
        return list(self._by_name.values())


# ------------------------------------------------------------------ catálogo por defecto
def _build_default() -> SemanticFieldRegistry:
    reg = SemanticFieldRegistry()

    # ── EMPLOYEE ────────────────────────────────────────────────────────────────
    reg.add(FieldDef(
        "name", "employee", "string",
        ("nombre", "nombre completo", "persona", "empleado", "trabajador", "name"),
        ("count",),
    ))
    reg.add(FieldDef(
        "department", "employee", "string",
        ("departamento", "area", "seccion", "sección", "dpto", "department"),
        ("count", "distribution"),
    ))
    reg.add(FieldDef(
        "position", "employee", "string",
        ("puesto", "cargo", "rol", "posicion", "posición", "position", "job"),
        ("count", "distribution"),
    ))
    reg.add(FieldDef(
        "age", "employee", "int",
        ("edad", "anos", "años", "age", "anos cumplidos"),
        ("count", "mean", "median", "min", "max", "distribution", "percentile"),
        unit="años",
    ))
    reg.add(FieldDef(
        "active", "employee", "bool",
        ("activo", "activa", "en activo", "active", "vigente"),
        ("count",),
    ))
    reg.add(FieldDef(
        "hire_date", "employee", "date",
        ("fecha de alta", "fecha de entrada", "incorporacion", "fecha de incorporacion",
         "antiguedad", "antigüedad", "tiempo en la empresa", "hire_date", "years"),
        ("min", "max", "distribution", "trend"),
        description="Fecha de incorporación (no disponible en todos los empleados)",
    ))
    reg.add(FieldDef(
        "gender", "employee", "enum",
        ("genero", "género", "sexo", "gender"),
        ("count", "distribution"),
        description="Género (campo no disponible actualmente)",
    ))
    reg.add(FieldDef(
        "contract_type", "employee", "enum",
        ("tipo de contrato", "contrato", "indefinido", "temporal", "contract_type"),
        ("count", "distribution"),
    ))
    reg.add(FieldDef(
        "nationality", "employee", "string",
        ("nacionalidad", "pais", "país", "nationality"),
        ("count", "distribution"),
    ))

    # ── SHIFT ────────────────────────────────────────────────────────────────────
    reg.add(FieldDef(
        "shift_kind", "shift", "enum",
        ("turno", "tipo de turno", "jornada", "franja", "shift"),
        ("count", "distribution"),
    ))
    reg.add(FieldDef(
        "shift_hours", "shift", "float",
        ("horas", "horas de trabajo", "horas trabajadas", "horas planificadas"),
        ("sum", "mean", "median", "min", "max"),
        unit="horas",
    ))
    reg.add(FieldDef(
        "absence_days", "shift", "int",
        ("dias de baja", "días de baja", "ausencia", "ausencias", "absentismo",
         "bajas", "dias ausente", "dias de ausencia"),
        ("count", "sum", "mean", "median", "min", "max", "trend"),
        unit="días",
    ))
    reg.add(FieldDef(
        "absence_rate", "shift", "float",
        ("tasa de absentismo", "ratio de baja", "porcentaje de baja", "absence_rate",
         "indice de absentismo", "índice de absentismo"),
        ("mean", "trend", "distribution"),
        unit="%",
    ))

    # ── VACATION ────────────────────────────────────────────────────────────────
    reg.add(FieldDef(
        "vacation_balance", "vacation", "float",
        ("saldo de vacaciones", "dias de vacaciones", "días de vacaciones",
         "vacaciones disponibles", "balance vacaciones"),
        ("sum", "mean", "median", "min", "max"),
        unit="días",
    ))
    reg.add(FieldDef(
        "vacation_days_taken", "vacation", "int",
        ("vacaciones disfrutadas", "dias disfrutados", "vacaciones tomadas"),
        ("sum", "mean"),
        unit="días",
    ))

    # ── PAYROLL ─────────────────────────────────────────────────────────────────
    reg.add(FieldDef(
        "liquido", "payroll", "float",
        ("liquido", "líquido", "neto", "salario neto", "sueldo neto",
         "cuanto cobra", "cuánto cobra", "lo que le llega", "take home",
         "salario", "sueldo"),
        ("sum", "mean", "median", "min", "max", "percentile", "stddev", "trend"),
        permission="NOMINAS_IMPORTES",
        unit="€",
    ))
    reg.add(FieldDef(
        "total_devengado", "payroll", "float",
        ("devengado", "bruto", "salario bruto", "sueldo bruto", "total devengado",
         "gross", "antes de impuestos"),
        ("sum", "mean", "median", "min", "max", "percentile"),
        permission="NOMINAS_IMPORTES",
        unit="€",
    ))
    reg.add(FieldDef(
        "irpf", "payroll", "float",
        ("irpf", "retencion", "retención", "impuesto"),
        ("mean", "min", "max"),
        permission="NOMINAS_IMPORTES",
        unit="%",
    ))
    reg.add(FieldDef(
        "coste_empresa", "payroll", "float",
        ("coste empresa", "coste total", "coste laboral", "coste de personal",
         "gasto de personal", "coste patron", "coste patronal"),
        ("sum", "mean", "median", "min", "max"),
        permission="NOMINAS_IMPORTES",
        unit="€",
    ))

    # ── DOCUMENT ────────────────────────────────────────────────────────────────
    reg.add(FieldDef(
        "doc_type", "document", "string",
        ("tipo de documento", "contrato", "documento firmado", "doc_type"),
        ("count", "distribution"),
    ))
    reg.add(FieldDef(
        "doc_signed", "document", "bool",
        ("firmado", "tiene documento", "documento firmado", "signed"),
        ("count",),
    ))

    # ── TIMESHEET (ETT) ──────────────────────────────────────────────────────────
    reg.add(FieldDef(
        "tt_hours", "timesheet", "float",
        ("horas ett", "horas temporal", "horas trabajo temporal"),
        ("sum", "mean", "min", "max", "trend"),
        unit="horas",
    ))
    reg.add(FieldDef(
        "tt_cost", "timesheet", "float",
        ("coste ett", "coste trabajo temporal", "importe ett"),
        ("sum", "mean", "min", "max", "trend"),
        unit="€",
    ))

    return reg


field_registry: SemanticFieldRegistry = _build_default()

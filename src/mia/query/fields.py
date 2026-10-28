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
    "employee",
    "shift",
    "vacation",
    "payroll",
    "document",
    "timesheet",
    "candidate",
    "report",
    "system",
]

AggOp = Literal[
    "count",
    "sum",
    "mean",
    "median",
    "min",
    "max",
    "percentile",
    "stddev",
    "trend",
    "distribution",
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
    source: str = ""
    """Procedencia real (modelo.campo) para trazabilidad — nunca una tabla inventada."""
    granularity: str = ""
    """Nivel al que existe el dato: p. ej. «per_employee», «per_payslip», «per_shift_day», «per_month»."""
    min_group: int | None = None
    """Tamaño mínimo de grupo exigido antes de poder desagregar este campo por individuo (k-anonimato).
    Para nóminas replica (sin importarla, para no invertir la dependencia query→nominas) el mismo valor
    que ``mia.modules.rrhh.nominas.estadisticas.MIN_GROUP`` — ver test de consistencia en
    ``tests/test_query_fields.py`` que falla si alguna de las dos cambia sin la otra. None = sin
    restricción adicional de k-anonimato más allá del permiso."""


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

    def resolve_all(self, text: str) -> list[FieldDef]:
        """Todos los campos cuyo sinónimo aparece en *text* (una petición de informe suele mencionar
        varios: métricas Y dimensiones a la vez). Un campo aparece una sola vez, aunque coincidan varios
        de sus sinónimos; el orden refleja la posición del sinónimo más largo que coincidió con él,
        de izquierda a derecha en el texto."""
        norm = normalize_key(text)
        hits: dict[str, tuple[int, int]] = {}  # name -> (posición, -longitud) para ordenar
        for syn, fd in self._by_synonym.items():
            pos = norm.find(syn)
            if pos == -1:
                continue
            best = hits.get(fd.name)
            if best is None or len(syn) > -best[1]:
                hits[fd.name] = (pos, -len(syn))
        ordered_names = sorted(hits, key=lambda n: hits[n])
        return [self._by_name[n] for n in ordered_names]

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
    reg.add(
        FieldDef(
            "name",
            "employee",
            "string",
            ("nombre", "nombre completo", "persona", "empleado", "trabajador", "name"),
            ("count",),
            source="mia.data.Employee.name",
            granularity="per_employee",
        )
    )
    reg.add(
        FieldDef(
            "department",
            "employee",
            "string",
            ("departamento", "area", "seccion", "sección", "dpto", "department"),
            ("count", "distribution"),
            source="mia.data.Employee.department",
            granularity="per_employee",
        )
    )
    reg.add(
        FieldDef(
            "position",
            "employee",
            "string",
            ("puesto", "cargo", "rol", "posicion", "posición", "position", "job"),
            ("count", "distribution"),
            source="mia.data.Employee.position",
            granularity="per_employee",
        )
    )
    reg.add(
        FieldDef(
            "age",
            "employee",
            "int",
            ("edad", "anos", "años", "age", "anos cumplidos"),
            ("count", "mean", "median", "min", "max", "distribution", "percentile"),
            unit="años",
            source="mia.data.Employee.birth_date",
            granularity="per_employee",
        )
    )
    reg.add(
        FieldDef(
            "active",
            "employee",
            "bool",
            ("activo", "activa", "en activo", "active", "vigente"),
            ("count",),
            source="mia.data.Employee.active",
            granularity="per_employee",
        )
    )
    reg.add(
        FieldDef(
            "hire_date",
            "employee",
            "date",
            (
                "fecha de alta",
                "fecha de entrada",
                "incorporacion",
                "fecha de incorporacion",
                "antiguedad",
                "antigüedad",
                "tiempo en la empresa",
                "hire_date",
                "years",
            ),
            ("min", "max", "distribution", "trend"),
            description="Fecha de incorporación (no disponible en todos los empleados)",
            source="mia.data.Employee.hire_date",
            granularity="per_employee",
        )
    )
    reg.add(
        FieldDef(
            "gender",
            "employee",
            "enum",
            ("genero", "género", "sexo", "gender"),
            ("count", "distribution"),
            description="Género (campo no disponible actualmente)",
            source="mia.data.Employee (no implementado)",
            granularity="per_employee",
        )
    )
    reg.add(
        FieldDef(
            "contract_type",
            "employee",
            "enum",
            ("tipo de contrato", "contrato", "indefinido", "temporal", "contract_type"),
            ("count", "distribution"),
            source="mia.data.Employee.contract_type",
            granularity="per_employee",
        )
    )
    reg.add(
        FieldDef(
            "nationality",
            "employee",
            "string",
            ("nacionalidad", "pais", "país", "nationality"),
            ("count", "distribution"),
            source="mia.data.Employee.nationality",
            granularity="per_employee",
        )
    )

    # ── SHIFT ────────────────────────────────────────────────────────────────────
    reg.add(
        FieldDef(
            "shift_kind",
            "shift",
            "enum",
            ("turno", "tipo de turno", "jornada", "franja", "shift"),
            ("count", "distribution"),
            source="mia.data.ShiftDay.kind",
            granularity="per_shift_day",
        )
    )
    reg.add(
        FieldDef(
            "shift_hours",
            "shift",
            "float",
            ("horas", "horas de trabajo", "horas trabajadas", "horas planificadas"),
            ("sum", "mean", "median", "min", "max"),
            unit="horas",
            source="mia.data.ShiftDay (start_time/end_time)",
            granularity="per_shift_day",
        )
    )
    reg.add(
        FieldDef(
            "absence_days",
            "shift",
            "int",
            (
                "dias de baja",
                "días de baja",
                "ausencia",
                "ausencias",
                "absentismo",
                "bajas",
                "dias ausente",
                "dias de ausencia",
            ),
            ("count", "sum", "mean", "median", "min", "max", "trend"),
            unit="días",
            source="mia.modules.rrhh.turnos.periods.absence_periods",
            granularity="per_shift_day",
        )
    )
    reg.add(
        FieldDef(
            "absence_rate",
            "shift",
            "float",
            (
                "tasa de absentismo",
                "ratio de baja",
                "porcentaje de baja",
                "absence_rate",
                "indice de absentismo",
                "índice de absentismo",
            ),
            ("mean", "trend", "distribution"),
            unit="%",
            source="calculado: absence_days / días del periodo",
            granularity="per_month",
        )
    )

    # ── VACATION ────────────────────────────────────────────────────────────────
    reg.add(
        FieldDef(
            "vacation_balance",
            "vacation",
            "float",
            (
                "vacaciones",
                "saldo de vacaciones",
                "dias de vacaciones",
                "días de vacaciones",
                "vacaciones disponibles",
                "balance vacaciones",
            ),
            ("sum", "mean", "median", "min", "max"),
            unit="días",
            source="mia.data.VacationBalance.current_balance",
            granularity="per_employee",
        )
    )
    reg.add(
        FieldDef(
            "vacation_days_taken",
            "vacation",
            "int",
            ("vacaciones disfrutadas", "dias disfrutados", "vacaciones tomadas"),
            ("sum", "mean"),
            unit="días",
            source="mia.data.Vacation.total_days",
            granularity="per_request",
        )
    )

    # ── PAYROLL ─────────────────────────────────────────────────────────────────
    # min_group=3 refleja mia.modules.rrhh.nominas.estadisticas.MIN_GROUP (no se importa aquí para no
    # invertir la dependencia query→nominas; ver tests/test_query_fields.py para la prueba de
    # consistencia). Cualquier plan que toque un campo con min_group debe ejecutarse a través de las
    # herramientas de nóminas ya auditadas (ranking_salarial/estadisticas_salariales), nunca con una
    # consulta genérica nueva que pueda desagregar por debajo de ese umbral.
    reg.add(
        FieldDef(
            "liquido",
            "payroll",
            "float",
            (
                "liquido",
                "líquido",
                "neto",
                "salario neto",
                "sueldo neto",
                "cuanto cobra",
                "cuánto cobra",
                "lo que le llega",
                "take home",
                "salario",
                "sueldo",
            ),
            ("sum", "mean", "median", "min", "max", "percentile", "stddev", "trend"),
            permission="NOMINAS_IMPORTES",
            unit="€",
            source="mia.modules.rrhh.nominas.estadisticas (PDF de nómina, vía SharePoint)",
            granularity="per_payslip",
            min_group=3,
        )
    )
    reg.add(
        FieldDef(
            "total_devengado",
            "payroll",
            "float",
            ("devengado", "bruto", "salario bruto", "sueldo bruto", "total devengado", "gross", "antes de impuestos"),
            ("sum", "mean", "median", "min", "max", "percentile"),
            permission="NOMINAS_IMPORTES",
            unit="€",
            source="mia.modules.rrhh.nominas.estadisticas (PDF de nómina, vía SharePoint)",
            granularity="per_payslip",
            min_group=3,
        )
    )
    reg.add(
        FieldDef(
            "irpf",
            "payroll",
            "float",
            ("irpf", "retencion", "retención", "impuesto"),
            ("mean", "min", "max"),
            permission="NOMINAS_IMPORTES",
            unit="%",
            source="mia.modules.rrhh.nominas.estadisticas (PDF de nómina, vía SharePoint)",
            granularity="per_payslip",
            min_group=3,
        )
    )
    reg.add(
        FieldDef(
            "coste_empresa",
            "payroll",
            "float",
            (
                "coste empresa",
                "coste total",
                "coste laboral",
                "coste de personal",
                "gasto de personal",
                "coste patron",
                "coste patronal",
                "coste salarial",
                "costes salariales",
                "coste de los salarios",
                "coste en nominas",
                "costes en nominas",
                "coste de nomina",
                "costes de nomina",
                "gasto en nominas",
                "gastos en nominas",
                # Sin "en nominas"/"de personal": hoy no hay ninguna otra fuente de gasto conectada
                # (finanzas sigue sin backend real), así que "gasto"/"gastos" a secas también es esto —
                # ver incidencia real: "importe de gastos por departamento" no coincidía con ningún
                # sinónimo, el plan salía sin métricas de nómina y el guardián de exportación (sección 15)
                # nunca se activaba, exportando en silencio la última tabla ajena de la sesión.
                "gasto",
                "gastos",
                "importe de gastos",
                "gastos por departamento",
                "gasto por departamento",
            ),
            ("sum", "mean", "median", "min", "max"),
            permission="NOMINAS_IMPORTES",
            unit="€",
            source="mia.modules.rrhh.nominas.analisis_economico",
            granularity="per_payslip",
            min_group=3,
        )
    )

    # ── DOCUMENT ────────────────────────────────────────────────────────────────
    reg.add(
        FieldDef(
            "doc_type",
            "document",
            "string",
            ("tipo de documento", "contrato", "documento firmado", "doc_type"),
            ("count", "distribution"),
            source="mia.data (documentos firmados, SharePoint)",
            granularity="per_document",
        )
    )
    reg.add(
        FieldDef(
            "doc_signed",
            "document",
            "bool",
            ("firmado", "tiene documento", "documento firmado", "signed"),
            ("count",),
            source="mia.data (documentos firmados, SharePoint)",
            granularity="per_document",
        )
    )

    # ── TIMESHEET (ETT) ──────────────────────────────────────────────────────────
    reg.add(
        FieldDef(
            "tt_hours",
            "timesheet",
            "float",
            ("horas ett", "horas temporal", "horas trabajo temporal"),
            ("sum", "mean", "min", "max", "trend"),
            unit="horas",
            source="mia.data.TtTimesheet.hours",
            granularity="per_timesheet",
        )
    )
    reg.add(
        FieldDef(
            "tt_cost",
            "timesheet",
            "float",
            (
                "coste ett", "coste trabajo temporal", "importe ett",
                # Bastas a propósito (sin "coste"/"importe" delante): "trabajo temporal"/"boletines" a
                # secas también deben reconocerse como este dominio, no el de nómina -- incidencia real
                # 2026-10-28, "gastos en boletines trabajo temporal... por departamento" solo coincidía
                # con el sinónimo igual de basto "gasto"/"gastos" de coste_empresa (payroll), bloqueando
                # la exportación de boletines_tt como si fuera un informe de nómina mal encaminado.
                "trabajo temporal", "boletines", "temporalidad",
            ),
            ("sum", "mean", "min", "max", "trend"),
            unit="€",
            source="mia.data.TtTimesheet.cost",
            granularity="per_timesheet",
        )
    )

    return reg


field_registry: SemanticFieldRegistry = _build_default()

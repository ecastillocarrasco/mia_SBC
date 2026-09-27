"""Transformaciones de selección, nóminas, documentos firmados y trabajo temporal."""

from __future__ import annotations

import re
from typing import Any

from mia.sources.mappers.common import (
    MapContext,
    boolean,
    ddmmyyyy,
    email,
    number,
    person_field,
    sp_datetime,
    sp_local_date,
    text,
)
from mia.text import normalize_key

Row = dict[str, Any]
FOLDER = 1


def _is_folder(item: dict[str, Any]) -> bool:
    return int(item.get("FileSystemObjectType") or 0) == FOLDER


# ------------------------------------------------------------------ selección
def candidate(item: dict[str, Any], ctx: MapContext) -> list[Row]:
    name = (
        " ".join(filter(None, [text(item.get("FirstName")), text(item.get("Title"))]))
        or f"Candidatura {item['ID']}"
    )
    department = text(item.get("DepartamentoCV"))
    return [
        {
            "sp_id": int(item["ID"]),
            "name": name,
            "name_key": normalize_key(name),
            "email": email(item.get("EMail")),
            "phone": text(item.get("Telefono")),
            "department": department,
            "department_key": normalize_key(department) or None,
            "experience": text(item.get("ExpPrevia")),
            "languages": text(item.get("Idiomas")),
            "status": text(item.get("EstadoCV")),
            "comments": text(item.get("ComentariosCV")),
            "applied_on": sp_local_date(item.get("Fecha"), ctx.tz),
            "created_at": sp_datetime(item.get("Created")),
        }
    ]


_CV_ID = re.compile(r"^(\d+)(?:\..*)?$")


def cv_document(item: dict[str, Any], ctx: MapContext) -> list[Row]:
    """El nombre del fichero es el ID de la candidatura: 8316.pdf, 8317.docx, 8324."""
    if _is_folder(item) or not item.get("FileRef"):
        return []
    name = str(item.get("FileLeafRef") or "")
    match = _CV_ID.match(name.strip())
    return [
        {
            "sp_id": int(item["ID"]),
            "candidate_id": int(match.group(1)) if match else None,
            "file_name": name,
            "file_ref": str(item["FileRef"]),
            "modified_at": sp_datetime(item.get("Modified")),
        }
    ]


# ------------------------------------------------------------------ nóminas (NOM-001)
MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}
_PERIOD = re.compile(r"^(20\d{2})[-_](1[0-2]|0?[1-9])(?=[_-]|\.|$)")
_YEAR = re.compile(r"^(20\d{2})")


def _month_in_text(value: str | None) -> int | None:
    key = normalize_key(value)
    for name, number_ in MONTHS.items():
        if re.search(rf"(?:^| ){name}(?: |$)", key):
            return number_
    return None


def payslip_period(file_name: str | None, label: str | None) -> tuple[int | None, int | None, bool]:
    """(año, mes, especial). «2026-08_Agosto.pdf» → (2026, 8, False); «2025-71_Extra Julio» → (2025, 7, True).

    El mes de MesNomina manda sobre el del nombre; un código no mensual (71, 122…) marca paga especial.
    """
    name = (file_name or "").strip()
    year_match = _YEAR.match(name)
    year = int(year_match.group(1)) if year_match else None
    period = _PERIOD.match(name)
    month = int(period.group(2)) if period else None
    special = bool(year_match) and period is None
    labelled = _month_in_text(label)
    if labelled is not None:
        month = labelled
    elif month is None:
        month = _month_in_text(name)
    return year, month, special


def payslip(item: dict[str, Any], ctx: MapContext) -> list[Row]:
    if _is_folder(item):
        return []
    name, mail = person_field(item.get("UsuarioNomina"))
    file_name = text(item.get("FileLeafRef"))
    label = text(item.get("MesNomina"))
    year, month, special = payslip_period(file_name, label)
    return [
        {
            "sp_id": int(item["ID"]),
            "person_key": item.get("_person_key"),
            "employee_name": name,
            "employee_email": mail,
            "year": year,
            "month": month,
            "period": f"{year:04d}-{month:02d}" if year and month else None,
            "label": label,
            "special": special,
            "read": boolean(item.get("Leido")) if item.get("Leido") is not None else None,
            "file_name": file_name,
            "created_at": sp_datetime(item.get("Created")),
        }
    ]


# ------------------------------------------------------------------ documentos firmados (FIR-001)
_DOC_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Reconocimiento médico",
        ("reconocimiento medico", "revision medica", "aptitud medica", "vigilancia salud"),
    ),
    ("Prórroga contractual", ("prorroga",)),
    ("Anexo contractual", ("anexo contrato", "anexo contractual")),
    ("Contrato", ("contrato",)),
    ("Protección de datos", ("proteccion de datos", "lopd", "rgpd")),
    ("Prevención", ("prevencion", "prl", "riesgos laborales")),
    (
        "Normativa",
        (
            "normativa",
            "reglamento",
            "protocolo",
            "procedimiento",
            "politica seguridad",
            "seguridad de la informacion",
            "seguridad sistemas informacion",
        ),
    ),
    ("Comunicación", ("comunicado", "comunicacion", "notificacion")),
)


def document_type(file_name: str | None) -> str:
    key = normalize_key(file_name)
    tokens = set(key.split())
    if "rm" in tokens:
        return "Reconocimiento médico"
    for label, needles in _DOC_RULES:
        if any(needle in key for needle in needles):
            return label
    if tokens & {"formacion", "curso", "cursos"}:  # palabra completa: «informacion» no es formación
        return "Formación"
    return "Otros"


def signed_document(item: dict[str, Any], ctx: MapContext) -> list[Row]:
    if _is_folder(item):
        return []
    file_name = text(item.get("FileLeafRef"))
    year = re.search(r"(?<!\d)(20\d{2})(?!\d)", file_name or "")
    return [
        {
            "sp_id": int(item["ID"]),
            "person_key": item.get("_person_key"),
            "doc_type": document_type(file_name),
            "file_name": file_name,
            "doc_year": int(year.group(1)) if year else None,
            "created_at": sp_datetime(item.get("Created")),
        }
    ]


# ------------------------------------------------------------------ trabajo temporal
def tt_company(item: dict[str, Any], ctx: MapContext) -> list[Row]:
    return [
        {
            "sp_id": int(item["ID"]),
            "name": text(item.get("Title")) or f"Empresa {item['ID']}",
            "cif": text(item.get("CIFEmpresaTT")),
            "email": email(item.get("MailEmpresaTT")),
            "phone": text(item.get("TelefonoEmpresaTT")),
        }
    ]


def tt_worker(item: dict[str, Any], ctx: MapContext) -> list[Row]:
    name = " ".join(filter(None, [text(item.get("NombreEmpleadoTT")), text(item.get("ApellidosEmpleadoTT"))]))
    return [
        {
            "sp_id": int(item["ID"]),
            "name": name or f"Trabajador {item['ID']}",
            "name_key": normalize_key(name),
            "department": text(item.get("DepartamentoEmpleadoTT")),
            "company": text(item.get("EmpresaTTEmpleadoTT")),
            "email": email(item.get("MailEmpleadoTT")),
            "phone": text(item.get("TelefonoEmpleadoTT")),
            "visible": item.get("VisibleEmpleadoTT") is None or boolean(item.get("VisibleEmpleadoTT")),
        }
    ]


def _int_or_none(value: Any) -> int | None:
    parsed = number(value)
    return int(parsed) if parsed is not None else None


def tt_timesheet(item: dict[str, Any], ctx: MapContext) -> list[Row]:
    department = text(item.get("DepartamentoBoletinTT"))
    return [
        {
            "sp_id": int(item["ID"]),
            "day": sp_local_date(item.get("FechaBoletinTT"), ctx.tz) or ddmmyyyy(item.get("FechaBoletinTT")),
            "worker_name": text(item.get("EmpleadoBoletinTT")),
            "worker_id": _int_or_none(item.get("IDEmpleadoBoletinTT")),
            "company": text(item.get("EmpresaBoletinTT")),
            "company_id": _int_or_none(item.get("IDEmpresaBoletinTT")),
            "department": department,
            "department_key": normalize_key(department) or None,
            "status": text(item.get("EstadoBoletinTT")),
            "start_time": text(item.get("HoraEntradaBoletinTT")),
            "end_time": text(item.get("HoraSalidaBoletinTT")),
            "hours_normal": number(item.get("HorasNormalesBoletinTT")),
            "hours_night": number(item.get("HorasNocturnasBoletinTT")),
            "hours_total": number(item.get("HorasTotalesBoletinTT")),
            "diet": number(item.get("DietaBoletinTT")),
            "amount": number(item.get("ImporteBoletinTT")),
        }
    ]


# ------------------------------------------------------------------ fase 4b
def new_hire(item: dict[str, Any], ctx: MapContext) -> list[Row]:
    name = " ".join(filter(None, [text(item.get("Nombre")), text(item.get("Apellidos"))])) or text(
        item.get("Title")
    )
    return [
        {
            "sp_id": int(item["ID"]),
            "name": name or f"Alta {item['ID']}",
            "name_key": normalize_key(name),
            "department": text(item.get("Departamento")),
            "position": text(item.get("Puesto")),
            "email": email(item.get("Mail")),
            "account": text(item.get("Usuario365") or item.get("userAccount")),
            "person_key": text(item.get("DNI")),  # ya seudonimizado en la ingesta
            "created_at": sp_datetime(item.get("Created")),
        }
    ]


def _decimal_es(value: Any) -> float | None:
    raw = str(value or "").strip()
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    return number(raw)


def tt_rate(item: dict[str, Any], ctx: MapContext) -> list[Row]:
    company = text(item.get("Title")) or f"Empresa {item['ID']}"
    return [
        {
            "sp_id": int(item["ID"]),
            "company": company,
            "company_key": normalize_key(company),
            "normal_start": text(item.get("HInicioNormal")),
            "normal_end": text(item.get("HFinNormal")),
            "night_start": text(item.get("HInicioNocturna")),
            "night_end": text(item.get("HFinNocturna")),
            "price_normal": _decimal_es(item.get("PrecioHNormal")),
            "price_night": _decimal_es(item.get("PrecioHNocturna")),
            "price_diet": _decimal_es(item.get("PrecioDieta")),
            "short_contract_surcharge": _decimal_es(item.get("RecargoCortaDuracion")),
        }
    ]


def tt_communication(item: dict[str, Any], ctx: MapContext) -> list[Row]:
    if _is_folder(item):
        return []
    return [
        {
            "sp_id": int(item["ID"]),
            "title": text(item.get("Title")),
            "file_name": text(item.get("FileLeafRef")),
            "created_at": sp_datetime(item.get("Created")),
        }
    ]


def document_type_config(site: str) -> Any:
    def mapper(item: dict[str, Any], ctx: MapContext) -> list[Row]:
        name = text(item.get("Title"))
        if not name:
            return []
        return [
            {
                "site": site,
                "sp_id": int(item["ID"]),
                "name": name,
                "name_key": normalize_key(name),
                "sign_all": boolean(item.get("FirmarTodas")) if item.get("FirmarTodas") is not None else None,
                "requires_authorization": (
                    boolean(item.get("ReqAutorizacion")) if item.get("ReqAutorizacion") is not None else None
                ),
            }
        ]

    return mapper

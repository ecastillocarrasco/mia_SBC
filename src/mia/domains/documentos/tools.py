"""Documentación firmada: qué documentos tiene cada persona y a quién le falta alguno.

FIR-001: solo se informa de la existencia y el tipo; nunca del contenido ni de las firmas.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from mia.auth import Permission
from mia.conversation import Tool, ToolContext, ToolRegistry, ToolResult, ToolStatus
from mia.data import Employee, SignedDocument
from mia.domains.common import (
    MAX_ROWS_FOR_MODEL,
    Deps,
    PersonaParams,
    department_problem,
    focus_person,
    person_problem,
    resolve_department,
    resolve_person,
    table,
)
from mia.text import normalize_key

RULE = "FIR-001: solo existencia y tipo del documento; nunca su contenido ni la firma."
TYPES = (
    "Contrato, Prórroga contractual, Anexo contractual, Protección de datos, Prevención, Normativa, "
    "Comunicación, Formación, Reconocimiento médico, Otros"
)


class DocumentosPersonaParams(PersonaParams):
    tipo: str | None = Field(default=None, description=f"Tipo: {TYPES}")
    anio: int | None = None


def documentos_persona(deps: Deps) -> Tool:
    async def handler(p: DocumentosPersonaParams, ctx: ToolContext) -> ToolResult:
        async with deps.db.session() as db:
            match = await resolve_person(db, p)
            if match.employee is None:
                return person_problem(match, p.nombre)
            e = match.employee
            docs: list[SignedDocument] = []
            if e.person_key:
                stmt = select(SignedDocument).where(SignedDocument.person_key == e.person_key)
                docs = list((await db.scalars(stmt.order_by(SignedDocument.created_at.desc()))).all())
            fresh = await deps.freshness(db, "documentos_firmados")
        if p.tipo:
            docs = [d for d in docs if normalize_key(p.tipo) in normalize_key(d.doc_type)]
        if p.anio:
            docs = [d for d in docs if d.doc_year == p.anio]
        items = [{"tipo": d.doc_type, "documento": d.file_name, "anio": d.doc_year} for d in docs]
        summary: dict[str, Any] = {
            "persona": e.name,
            "total": len(items),
            "por_tipo": dict(Counter(d.doc_type for d in docs)),
            "documentos": items[:MAX_ROWS_FOR_MODEL],
            "regla": RULE,
            **fresh,
        }
        return ToolResult(
            ToolStatus.OK,
            summary,
            table(f"Documentos de {e.name}", ["Tipo", "Documento", "Año"], [list(i.values()) for i in items]),
            focus_person(e),
        )

    return Tool(
        "documentos_persona",
        "Documentos firmados de una persona (contratos, protección de datos, prevención…): solo tipo.",
        DocumentosPersonaParams,
        handler,
        permission=Permission.DOCUMENTOS_LEER,
        audit_resource="documentos",
    )


class FaltantesParams(BaseModel):
    tipo: str = Field(description=f"Tipo de documento: {TYPES}")
    departamento: str | None = None


def documentos_faltantes(deps: Deps) -> Tool:
    async def handler(p: FaltantesParams, ctx: ToolContext) -> ToolResult:
        async with deps.db.session() as db:
            dept = await resolve_department(db, p.departamento)
            if dept.status is not ToolStatus.OK:
                return department_problem(dept, p.departamento)
            stmt = select(Employee).where(Employee.active.is_(True))
            if dept.key:
                stmt = stmt.where(Employee.department_key == dept.key)
            employees = list((await db.scalars(stmt.order_by(Employee.name))).all())
            docs = (await db.execute(select(SignedDocument.person_key, SignedDocument.doc_type))).all()
            fresh = await deps.freshness(db, "documentos_firmados", "empleados")
        wanted = normalize_key(p.tipo)
        having = {k for k, t in docs if k and wanted in normalize_key(t)}
        missing = [e for e in employees if e.person_key not in having]
        summary: dict[str, Any] = {
            "tipo": p.tipo,
            "departamento": dept.name or "toda la plantilla activa",
            "plantilla_activa": len(employees),
            "sin_documento": len(missing),
            "regla": RULE,
            **fresh,
        }
        if len(missing) <= MAX_ROWS_FOR_MODEL:
            summary["personas"] = [e.name for e in missing]
        return ToolResult(
            ToolStatus.OK,
            summary,
            table(f"Sin «{p.tipo}»", ["Persona", "Departamento"], [[e.name, e.department] for e in missing]),
        )

    return Tool(
        "documentos_faltantes",
        "Quién de la plantilla activa no tiene firmado un tipo de documento.",
        FaltantesParams,
        handler,
        permission=Permission.DOCUMENTOS_LEER,
        audit_resource="documentos",
    )


def register(registry: ToolRegistry, deps: Deps) -> None:
    for factory in (documentos_persona, documentos_faltantes):
        registry.register(factory(deps))

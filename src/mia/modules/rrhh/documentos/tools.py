"""Documentación firmada: qué documentos tiene cada persona y a quién le falta alguno.

FIR-001: solo se informa de la existencia y el tipo; nunca del contenido ni de las firmas.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from mia.auth import Permission
from mia.conversation import Tool, ToolContext, ToolRegistry, ToolResult, ToolStatus
from mia.data import DocumentTypeConfig, Employee, SignedDocument
from mia.modules.rrhh.common import (
    MAX_ROWS_FOR_MODEL,
    CohortParams,
    Deps,
    PersonaParams,
    department_problem,
    document_entry,
    focus_person,
    no_population,
    person_problem,
    population_state,
    previous_population,
    resolve_department,
    resolve_person,
    table,
    wants_previous,
)
from mia.modules.rrhh.content import MAX_BYTES, content_unavailable, document_text
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
        items = [
            {
                "tipo": d.doc_type,
                "documento": d.file_name,
                "anio": d.doc_year,
                "enlace": f"/api/documents/documento/{d.sp_id}",
            }
            for d in docs
        ]
        summary: dict[str, Any] = {
            "persona": e.name,
            "total": len(items),
            "por_tipo": dict(Counter(d.doc_type for d in docs)),
            "documentos": items[:MAX_ROWS_FOR_MODEL],
            "regla": RULE,
            **fresh,
        }
        view = table(
            f"Documentos de {e.name}", ["Tipo", "Documento", "Año", "Enlace"], [list(i.values()) for i in items]
        )
        if ctx.user.has(Permission.DOCUMENTOS_CONTENIDO):
            view["documents"] = [
                document_entry(
                    "documento",
                    d.sp_id,
                    d.file_name or d.doc_type,
                    subtitle=d.doc_type,
                    date=str(d.doc_year) if d.doc_year else None,
                )
                for d in docs[:36]
            ]
        return ToolResult(ToolStatus.OK, summary, view, focus_person(e))

    return Tool(
        "documentos_persona",
        "Documentos firmados de una persona (contratos, protección de datos, prevención…): solo tipo.",
        DocumentosPersonaParams,
        handler,
        permission=Permission.DOCUMENTOS_LEER,
        audit_resource="documentos",
    )


class FaltantesParams(CohortParams):
    tipo: str | None = Field(
        default=None,
        description=f"Tipo: {TYPES}. Sin tipo: los que TODA la plantilla debe firmar (FirmarTodas)",
    )
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
            if wants_previous(p, ctx):
                if (previous := previous_population(ctx, p.resultado)) is None:
                    return no_population()
                stmt = stmt.where(Employee.sp_id.in_(previous["empleado_ids"]))
            employees = list((await db.scalars(stmt.order_by(Employee.name))).all())
            docs = (
                await db.execute(select(SignedDocument.person_key, SignedDocument.doc_type, SignedDocument.file_name))
            ).all()
            fresh = await deps.freshness(db, "documentos_firmados", "empleados")
        if p.tipo:
            wanted = [normalize_key(p.tipo)]
        else:
            async with deps.db.session() as db:
                mandatory = (
                    await db.scalars(select(DocumentTypeConfig.name_key).where(DocumentTypeConfig.sign_all.is_(True)))
                ).all()
            wanted = list(dict.fromkeys(mandatory))
            if not wanted:
                return ToolResult(ToolStatus.NOT_FOUND, "No hay tipos marcados como obligatorios (FirmarTodas).")
        missing_by_type = {}
        for w in wanted:
            having = {k for k, t, f in docs if k and (w in normalize_key(t) or w in normalize_key(f))}
            missing_by_type[w] = [e for e in employees if e.person_key not in having]
        missing = sorted(
            {e.sp_id: e for group in missing_by_type.values() for e in group}.values(), key=lambda e: e.name
        )
        summary: dict[str, Any] = {
            "tipo": p.tipo or "obligatorios (FirmarTodas)",
            "faltan_por_tipo": {k: len(v) for k, v in missing_by_type.items()},
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
            table(
                f"Sin «{p.tipo or 'documentos obligatorios'}»",
                ["Persona", "Departamento"],
                [[e.name, e.department] for e in missing],
            ),
            population_state(f"sin «{p.tipo or 'documentos obligatorios'}»", missing),
        )

    return Tool(
        "documentos_faltantes",
        "Quién de la plantilla activa no tiene firmado un tipo de documento.",
        FaltantesParams,
        handler,
        permission=Permission.DOCUMENTOS_LEER,
        audit_resource="documentos",
    )


class SinParametros(BaseModel):
    pass


def maestros(deps: Deps) -> Tool:
    async def handler(_: SinParametros, ctx: ToolContext) -> ToolResult:
        async with deps.db.session() as db:
            rows = list((await db.scalars(select(DocumentTypeConfig))).all())
        by_key: dict[str, dict[str, Any]] = {}
        for r in rows:
            entry = by_key.setdefault(r.name_key, {"tipo": r.name, "en_rrhh": False, "en_portal": False})
            entry[f"en_{r.site}"] = True
            if r.site == "rrhh":
                entry["firmar_todas"] = r.sign_all
            entry[f"autorizacion_{r.site}"] = r.requires_authorization
        items = sorted(by_key.values(), key=lambda x: x["tipo"])
        for item in items:
            if item["en_rrhh"] and item["en_portal"]:
                item["autorizacion_coincide"] = item.get("autorizacion_rrhh") == item.get("autorizacion_portal")
        return ToolResult(
            ToolStatus.OK,
            {
                "tipos": items,
                "solo_en_rrhh": [i["tipo"] for i in items if not i["en_portal"]],
                "solo_en_portal": [i["tipo"] for i in items if not i["en_rrhh"]],
            },
            table(
                "Maestros de tipos documentales",
                ["Tipo", "RRHH", "Portal", "Firmar todas", "Autorización coincide"],
                [
                    [i["tipo"], i["en_rrhh"], i["en_portal"], i.get("firmar_todas"), i.get("autorizacion_coincide")]
                    for i in items
                ],
            ),
        )

    return Tool(
        "maestros_documentales",
        "Tipos documentales de firma (RRHH y portal): cuáles son obligatorios "
        "para todos y diferencias entre ambos maestros.",
        SinParametros,
        handler,
        permission=Permission.DOCUMENTOS_LEER,
    )


# ------------------------------------------------------------------ cobertura documental agregada
class CoberturaDocumentalParams(BaseModel):
    departamento: str | None = Field(default=None, description="Limitar a un departamento")
    anio: int | None = Field(default=None, description="Filtrar por año del documento")


def cobertura_documental(deps: Deps) -> Tool:
    async def handler(p: CoberturaDocumentalParams, ctx: ToolContext) -> ToolResult:
        async with deps.db.session() as db:
            dept = await resolve_department(db, p.departamento)
            if dept.status is not ToolStatus.OK:
                return department_problem(dept, p.departamento)
            emp_stmt = select(Employee).where(Employee.active.is_(True))
            if dept.key:
                emp_stmt = emp_stmt.where(Employee.department_key == dept.key)
            employees = list((await db.scalars(emp_stmt)).all())
            keys = {e.person_key for e in employees if e.person_key}

            doc_stmt = select(SignedDocument.person_key, SignedDocument.doc_type)
            if keys:
                doc_stmt = doc_stmt.where(SignedDocument.person_key.in_(keys))
            if p.anio:
                doc_stmt = doc_stmt.where(SignedDocument.doc_year == p.anio)
            docs = (await db.execute(doc_stmt)).all()

            type_configs = list((await db.scalars(select(DocumentTypeConfig))).all())

        total = len(employees)
        if total == 0:
            return ToolResult(ToolStatus.NOT_FOUND, {"nota": "Sin empleados activos."})

        # Count distinct types per person
        by_type: dict[str, set[str]] = defaultdict(set)
        for person_key, doc_type in docs:
            if person_key and doc_type:
                by_type[normalize_key(doc_type)].add(person_key)

        # Build coverage per type name
        type_names = sorted({r.name for r in type_configs})
        rows = []
        for name in type_names:
            key = normalize_key(name)
            count = len(by_type.get(key, set()))
            pct = round(count / total * 100)
            missing = total - count
            rows.append([name, count, missing, f"{pct}%"])

        rows.sort(key=lambda r: -r[1])  # descending by signed count

        return ToolResult(
            ToolStatus.OK,
            {
                "plantilla_activa": total,
                "ambito": dept.name or "toda la empresa",
                "anio": p.anio,
                "cobertura": [
                    {"tipo": r[0], "firmado_por": r[1], "faltante": r[2], "porcentaje": r[3]}
                    for r in rows
                ],
            },
            table(
                "Cobertura de documentos firmados",
                ["Tipo de documento", "Firmado por", "Faltante", "Cobertura"],
                rows,
            ),
        )

    return Tool(
        "cobertura_documental",
        "Cobertura de documentos firmados: para cada tipo de documento, cuántas personas de la plantilla "
        "activa lo tienen firmado y cuántas no. Responde «¿qué % tiene firmado el contrato?».",
        CoberturaDocumentalParams,
        handler,
        permission=Permission.DOCUMENTOS_LEER,
    )


def register(registry: ToolRegistry, deps: Deps) -> None:
    for factory in (documentos_persona, documentos_faltantes, leer_documento, maestros, cobertura_documental):
        registry.register(factory(deps))


class LeerParams(PersonaParams):
    tipo: str | None = Field(default=None, description=f"Tipo del documento: {TYPES}")
    documento: str | None = Field(default=None, description="Nombre (o parte) del fichero, si hay varios del tipo")


def leer_documento(deps: Deps) -> Tool:
    async def handler(p: LeerParams, ctx: ToolContext) -> ToolResult:
        if problem := content_unavailable(deps):
            return problem
        async with deps.db.session() as db:
            match = await resolve_person(db, p)
            if match.employee is None:
                return person_problem(match, p.nombre)
            e = match.employee
            docs: list[SignedDocument] = []
            if e.person_key:
                docs = list(
                    (await db.scalars(select(SignedDocument).where(SignedDocument.person_key == e.person_key))).all()
                )
        if p.tipo:
            docs = [d for d in docs if normalize_key(p.tipo) in normalize_key(d.doc_type)]
        if p.documento:
            docs = [d for d in docs if normalize_key(p.documento) in normalize_key(d.file_name)]
        if not docs:
            return ToolResult(ToolStatus.NOT_FOUND, {"mensaje": "No hay ningún documento así"})
        # Con tipo especificado y varios del mismo tipo → el más reciente (sin pedir más input al usuario)
        if len(docs) > 1 and p.tipo:
            docs = sorted(docs, key=lambda d: (d.doc_year or 0, d.created_at or d.sp_id), reverse=True)
        elif len(docs) > 1:
            return ToolResult(
                ToolStatus.AMBIGUOUS,
                {
                    "documentos": [{"tipo": d.doc_type, "documento": d.file_name} for d in docs[:20]],
                    "mensaje": "Indica el tipo de documento",
                },
            )
        doc = docs[0]
        try:
            content = await deps.sharepoint.download_item_file("DocumentosFirmadosV2", doc.sp_id, MAX_BYTES)
            text = document_text(content)
        except Exception as exc:
            return ToolResult(ToolStatus.SOURCE_UNAVAILABLE, f"No he podido abrir el documento: {type(exc).__name__}")
        if not text:
            return ToolResult(ToolStatus.ERROR, "El documento no tiene texto legible (¿es una imagen escaneada?)")
        view = {
            "persona": e.name,
            "tipo": doc.doc_type,
            "documento": doc.file_name,
            "texto": text[:6000],
            "regla": "FIR-001: se lee el contenido del documento; las firmas no se analizan.",
        }
        return ToolResult(ToolStatus.OK, view, None, focus_person(e))

    return Tool(
        "leer_documento",
        "Lee el contenido de un documento firmado de una persona (contrato, protección de datos, "
        "reconocimiento médico, normativa…) para responder sobre él. Con un tipo especificado y varios "
        "documentos del mismo tipo, lee el más reciente automáticamente.",
        LeerParams,
        handler,
        permission=Permission.DOCUMENTOS_CONTENIDO,
        audit_resource="documentos_contenido",
        timeout_seconds=45,
    )

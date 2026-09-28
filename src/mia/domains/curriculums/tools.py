"""Selección: candidaturas y búsqueda en el texto de los CVs.

SEL-001: se busca y se explica la evidencia de cada CV; no se clasifica ni se
descarta a nadie. El orden de los resultados es de coincidencia con la búsqueda,
no de idoneidad para el puesto.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from mia.auth import Permission
from mia.conversation import Tool, ToolContext, ToolRegistry, ToolResult, ToolStatus
from mia.data import Candidate, CvDocument, CvText
from mia.domains.common import MAX_ROWS_FOR_MODEL, Deps, fmt_date, table
from mia.domains.curriculums.search import CvSearchIndex
from mia.text import normalize_key

RULE = "SEL-001: resultados por coincidencia con la búsqueda, no un ranking de idoneidad. No descartes a nadie."


def _candidate_view(c: Candidate) -> dict[str, Any]:
    return {
        "candidato_id": c.sp_id,
        "nombre": c.name,
        "departamento": c.department,
        "estado": c.status,
        "fecha": fmt_date(c.applied_on),
        "idiomas": c.languages,
    }


# ------------------------------------------------------------------ búsqueda
class BuscarParams(BaseModel):
    consulta: str = Field(description="Qué se busca en los CVs: experiencia, puesto, idiomas, formación…")
    departamento: str | None = Field(default=None, description="Departamento de la candidatura (opcional)")
    estado: str | None = Field(default=None, description="Estado de la candidatura (opcional)")
    limite: int = Field(default=10, ge=1, le=30)


def buscar(deps: Deps) -> Tool:
    index: CvSearchIndex = deps.services.setdefault("cv_index", CvSearchIndex())

    async def handler(p: BuscarParams, ctx: ToolContext) -> ToolResult:
        if deps.llm is None:
            return ToolResult(ToolStatus.SOURCE_UNAVAILABLE, "La búsqueda de CVs no está configurada")
        model = deps.settings.curriculums.embedding_model if deps.settings else "text-embedding-3-small"
        vector = (await deps.llm.embed([p.consulta], model))[0]
        async with deps.db.session() as db:
            stmt = select(Candidate)
            if p.departamento:
                stmt = stmt.where(Candidate.department_key.like(f"%{normalize_key(p.departamento)}%"))
            if p.estado:
                stmt = stmt.where(Candidate.status.ilike(f"%{p.estado}%"))
            candidates = {c.sp_id: c for c in (await db.scalars(stmt)).all()}
            hits = await index.search(db, vector, allowed=set(candidates), limit=p.limite)
            fresh = await deps.freshness(db, "curriculums", "cv_docs")
        if not hits:
            return ToolResult(
                ToolStatus.NOT_FOUND,
                {"mensaje": "Ningún CV indexado encaja con la búsqueda y los filtros.", **fresh},
            )
        seen: set[str] = set()
        results = []
        for h in hits:  # una persona con varias candidaturas aparece una vez (fallo real: «dos CV» del mismo)
            c = candidates[h.candidate_id]
            key = person_identity(c)
            if key in seen:
                continue
            seen.add(key)
            results.append({**_candidate_view(c), "evidencia": h.evidence})
        rows = [[r["nombre"], r["departamento"], r["estado"], r["fecha"], r["evidencia"][:160]] for r in results]
        return ToolResult(
            ToolStatus.OK,
            {"consulta": p.consulta, "coincidencias": results, "regla": RULE, **fresh},
            table(f"CVs: {p.consulta}", ["Candidatura", "Departamento", "Estado", "Fecha", "Evidencia"], rows),
        )

    return Tool(
        "buscar_candidatos",
        "Busca en el texto de los CVs (búsqueda semántica) y devuelve candidaturas con su evidencia.",
        BuscarParams,
        handler,
        permission=Permission.CURRICULUMS_LEER,
        audit_resource="curriculums",
    )


# ------------------------------------------------------------------ candidaturas
class CandidaturasParams(BaseModel):
    departamento: str | None = None
    estado: str | None = None
    desde: date | None = Field(default=None, description="Recibidas desde AAAA-MM-DD")
    hasta: date | None = Field(default=None, description="Recibidas hasta AAAA-MM-DD")


def candidaturas(deps: Deps) -> Tool:
    async def handler(p: CandidaturasParams, ctx: ToolContext) -> ToolResult:
        async with deps.db.session() as db:
            stmt = select(Candidate)
            if p.departamento:
                stmt = stmt.where(Candidate.department_key.like(f"%{normalize_key(p.departamento)}%"))
            if p.estado:
                stmt = stmt.where(Candidate.status.ilike(f"%{p.estado}%"))
            if p.desde:
                stmt = stmt.where(Candidate.applied_on >= p.desde)
            if p.hasta:
                stmt = stmt.where(Candidate.applied_on <= p.hasta)
            rows = list((await db.scalars(stmt.order_by(Candidate.applied_on.desc()))).all())
            fresh = await deps.freshness(db, "curriculums")
        summary: dict[str, Any] = {
            "total": len(rows),
            "por_estado": dict(Counter(c.status or "Sin estado" for c in rows).most_common()),
            "por_departamento": dict(Counter(c.department or "Sin dato" for c in rows).most_common(10)),
            **fresh,
        }
        if len(rows) <= MAX_ROWS_FOR_MODEL:
            summary["candidaturas"] = [_candidate_view(c) for c in rows]
        return ToolResult(
            ToolStatus.OK,
            summary,
            table(
                "Candidaturas",
                ["Nombre", "Departamento", "Estado", "Fecha"],
                [[c.name, c.department, c.status, fmt_date(c.applied_on)] for c in rows],
            ),
        )

    return Tool(
        "candidaturas",
        "Recuento y lista de candidaturas por departamento, estado o fechas.",
        CandidaturasParams,
        handler,
        permission=Permission.CURRICULUMS_LEER,
    )


# ------------------------------------------------------------------ ficha de candidatura
class CandidatoParams(BaseModel):
    candidato_id: int | None = None
    nombre: str | None = None


def ficha_candidato(deps: Deps) -> Tool:
    async def handler(p: CandidatoParams, ctx: ToolContext) -> ToolResult:
        async with deps.db.session() as db:
            if p.candidato_id is not None:
                matches = [c] if (c := await db.get(Candidate, p.candidato_id)) else []
            else:
                tokens = normalize_key(p.nombre).split()
                stmt = select(Candidate)
                for token in tokens:
                    stmt = stmt.where(Candidate.name_key.like(f"%{token}%"))
                matches = list((await db.scalars(stmt.limit(11))).all()) if tokens else []
            if len(matches) != 1:
                status = ToolStatus.AMBIGUOUS if matches else ToolStatus.NOT_FOUND
                return ToolResult(status, {"candidatos": [_candidate_view(c) for c in matches[:10]]})
            candidate = matches[0]
            cv = await db.scalar(select(CvText).where(CvText.candidate_id == candidate.sp_id))
            doc_id = await db.scalar(select(CvDocument.sp_id).where(CvDocument.candidate_id == candidate.sp_id))
        view = {
            **_candidate_view(candidate),
            "experiencia_declarada": candidate.experience,
            "comentarios": candidate.comments,
            "cv": ({"estado": cv.status, "extracto": (cv.text or "")[:2500]} if cv else {"estado": "sin CV indexado"}),
            "documento": f"/api/documents/cv/{doc_id}" if doc_id else None,
            "regla": RULE,
        }
        return ToolResult(ToolStatus.OK, view, {"type": "candidate_card", **view})

    return Tool(
        "ficha_candidato",
        "Datos de una candidatura y un extracto de su CV, para responder preguntas sobre ella.",
        CandidatoParams,
        handler,
        permission=Permission.CURRICULUMS_LEER,
        audit_resource="curriculums",
    )


def person_identity(c: Candidate) -> str:
    """Una fila de CurriculosVitae es una candidatura; la persona se identifica por email o, si no, por nombre."""
    return (c.email or "").lower() or c.name_key


def _terms(values: list[str] | None) -> list[str]:
    return [normalize_key(v) for v in values or [] if normalize_key(v)]


def _matches(haystack: str, term: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}", haystack) is not None


class FiltrarParams(BaseModel):
    todos: list[str] | None = Field(default=None, description="Términos que deben aparecer TODOS (y)")
    alguno: list[str] | None = Field(default=None, description="Basta con que aparezca ALGUNO (o)")
    excluir: list[str] | None = Field(default=None, description="Términos que NO deben aparecer («sin inglés»)")
    departamento: str | None = Field(default=None, description="Departamento de la candidatura")
    estado: str | None = None
    mostrar: int = Field(default=10, ge=1, le=40, description="Cuántas candidaturas listar")


def filtrar(deps: Deps) -> Tool:
    async def handler(p: FiltrarParams, ctx: ToolContext) -> ToolResult:
        required, anyof, excluded = _terms(p.todos), _terms(p.alguno), _terms(p.excluir)
        if not (required or anyof or excluded):
            return ToolResult(ToolStatus.INVALID_ARGUMENTS, "Indica al menos un término de búsqueda.")
        async with deps.db.session() as db:
            stmt = select(Candidate)
            if p.departamento:
                stmt = stmt.where(Candidate.department_key.like(f"%{normalize_key(p.departamento)}%"))
            if p.estado:
                stmt = stmt.where(Candidate.status.ilike(f"%{p.estado}%"))
            candidates = list((await db.scalars(stmt)).all())
            texts = {
                t.candidate_id: t.text or ""
                for t in (await db.scalars(select(CvText).where(CvText.status == "ok"))).all()
                if t.candidate_id is not None
            }
            fresh = await deps.freshness(db, "curriculums", "cv_docs")
        matched: list[tuple[Candidate, str]] = []
        for c in candidates:
            meta = normalize_key(" ".join(filter(None, [c.department, c.experience, c.languages, c.comments])))
            cv = normalize_key(texts.get(c.sp_id, ""))
            full = f"{meta} {cv}"
            if not all(_matches(full, t) for t in required):
                continue
            if anyof and not any(_matches(full, t) for t in anyof):
                continue
            if any(_matches(full, t) for t in excluded):
                continue
            wanted = required + anyof
            in_meta = any(_matches(meta, t) for t in wanted)
            in_cv = any(_matches(cv, t) for t in wanted)
            matched.append((c, "ambos" if in_meta and in_cv else "metadatos" if in_meta else "cv" if in_cv else "—"))
        matched.sort(key=lambda m: m[0].applied_on or date.min, reverse=True)
        people = {person_identity(c) for c, _ in matched}
        summary: dict[str, Any] = {
            "candidaturas": len(matched),
            "personas_unicas": len(people),
            "con_cv_indexado": sum(1 for c, _ in matched if c.sp_id in texts),
            "coincidencia": dict(Counter(origin for _, origin in matched)),
            "muestra": [{**_candidate_view(c), "coincide_en": origin} for c, origin in matched[: p.mostrar]],
            "regla": RULE + " Una fila es una candidatura: la misma persona puede tener varias.",
            **fresh,
        }
        rows = [[c.name, c.department, c.status, fmt_date(c.applied_on), origin] for c, origin in matched]
        return ToolResult(
            ToolStatus.OK if matched else ToolStatus.NOT_FOUND,
            summary,
            table("Candidaturas filtradas", ["Candidatura", "Departamento", "Estado", "Fecha", "Coincide en"], rows),
        )

    return Tool(
        "filtrar_candidatos",
        "Filtra candidaturas por términos exactos combinados (todos / alguno / excluir) en los datos de la "
        "candidatura y en el texto del CV, con recuento de candidaturas y personas únicas. Úsalo para "
        "«cuántos», «que cumplan», «con X e Y», «X o Y», «sin X»; buscar_candidatos es para parecido semántico.",
        FiltrarParams,
        handler,
        permission=Permission.CURRICULUMS_LEER,
        audit_resource="curriculums",
    )


def register(registry: ToolRegistry, deps: Deps) -> None:
    for factory in (buscar, filtrar, candidaturas, ficha_candidato):
        registry.register(factory(deps))

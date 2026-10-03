"""Selección: candidaturas y búsqueda en el texto de los CVs.

SEL-001: se busca y se explica la evidencia de cada CV; no se clasifica ni se
descarta a nadie. El orden de los resultados es de coincidencia con la búsqueda,
no de idoneidad para el puesto.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from mia.auth import Permission
from mia.conversation import Tool, ToolContext, ToolRegistry, ToolResult, ToolStatus
from mia.data import Candidate, CvDocument, CvText
from mia.modules.rrhh.common import MAX_ROWS_FOR_MODEL, Deps, document_entry, fmt_date, table
from mia.modules.rrhh.curriculums.requirements import (
    SEMANTIC_THRESHOLD,
    Evidence,
    Match,
    check_lexical,
    terms_for,
)
from mia.modules.rrhh.curriculums.search import CvSearchIndex
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
class ParecidosParams(BaseModel):
    consulta: str = Field(description="Perfil descrito en general: «alguien con experiencia en hoteles de lujo»")
    departamento: str | None = Field(default=None, description="Departamento de la candidatura (opcional)")
    estado: str | None = Field(default=None, description="Estado de la candidatura (opcional)")
    limite: int = Field(default=10, ge=1, le=30)


def parecidos(deps: Deps) -> Tool:
    index: CvSearchIndex = deps.services.setdefault("cv_index", CvSearchIndex())

    async def handler(p: ParecidosParams, ctx: ToolContext) -> ToolResult:
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
        "candidatos_parecidos",
        "Candidaturas cuyo CV se parece a un perfil descrito en general (búsqueda por significado). Para "
        "requisitos concretos («inglés», «cocina japonesa»…) usa buscar_candidatos.",
        ParecidosParams,
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
                matches = list((await db.scalars(stmt.limit(40))).all()) if tokens else []
            same_person = len({person_identity(c) for c in matches}) == 1
            if len(matches) > 1 and same_person:
                # Varias candidaturas de la MISMA persona (fallo real: «Gisella Terzolo» salía como ambigua).
                matches.sort(key=lambda c: c.applied_on or date.min, reverse=True)
                others = len(matches) - 1
                matches = matches[:1]
            else:
                others = 0
            if len(matches) != 1:
                status = ToolStatus.AMBIGUOUS if matches else ToolStatus.NOT_FOUND
                return ToolResult(status, {"candidatos": [_candidate_view(c) for c in matches[:10]]})
            candidate = matches[0]
            # El CV puede colgar de OTRA candidatura de la misma persona (fallo real: «no hay un CV disponible»).
            same = select(Candidate.sp_id).where(
                (Candidate.sp_id == candidate.sp_id)
                | (Candidate.email == candidate.email if candidate.email else Candidate.sp_id < 0)
                | (Candidate.name_key == candidate.name_key)
            )
            cv = (
                await db.scalars(
                    select(CvText)
                    .where(CvText.candidate_id.in_(same), CvText.status == "ok")
                    .order_by((CvText.candidate_id == candidate.sp_id).desc(), CvText.document_id.desc())
                )
            ).first() or await db.scalar(select(CvText).where(CvText.candidate_id.in_(same)))
            doc_id = await db.scalar(
                select(CvDocument.sp_id)
                .where(CvDocument.candidate_id.in_(same))
                .order_by((CvDocument.candidate_id == candidate.sp_id).desc(), CvDocument.sp_id.desc())
            )
        view = {
            **_candidate_view(candidate),
            **({"otras_candidaturas_de_la_misma_persona": others} if others else {}),
            "experiencia_declarada": candidate.experience,
            "comentarios": candidate.comments,
            "otros_datos_de_la_candidatura": candidate.extra or {},
            "cv": ({"estado": cv.status, "extracto": (cv.text or "")[:6000]} if cv else {"estado": "sin CV indexado"}),
            "documento": f"/api/documents/cv/{doc_id}" if doc_id else None,
            "regla": RULE,
        }
        card = {"type": "candidate_card", **view}
        if doc_id:
            card["documents"] = [document_entry("cv", doc_id, f"CV de {candidate.name}", subtitle=candidate.department)]
        return ToolResult(ToolStatus.OK, view, card)

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


class Requisito(BaseModel):
    termino: str = Field(description="Requisito tal como lo pide el usuario: «inglés», «cocina japonesa», «carné B»")
    equivalentes: list[str] = Field(
        default_factory=list,
        description="Formas en que puede aparecer escrito en un CV: sinónimos, traducciones, especialidades, "
        "niveles (p. ej. cocina japonesa → japonesa, japanese, sushi, washoku, itamae, ramen). Añádelos siempre.",
    )


class BuscarParams(BaseModel):
    requisitos: list[Requisito] = Field(min_length=1, description="TODOS los requisitos pedidos, uno por elemento")
    excluir: list[Requisito] = Field(
        default_factory=list, description="Lo que NO deben tener («sin inglés» → excluir inglés), con equivalentes"
    )
    departamento: str | None = Field(default=None, description="Departamento de la candidatura (filtro de metadatos)")
    estado: str | None = Field(default=None, description="Estado de la candidatura (opcional)")
    mostrar: int = Field(default=10, ge=1, le=40, description="Cuántas candidaturas enseñar («dame dos» → 2)")


def buscar(deps: Deps) -> Tool:
    index: CvSearchIndex = deps.services.setdefault("cv_index", CvSearchIndex())

    async def handler(p: BuscarParams, ctx: ToolContext) -> ToolResult:
        async with deps.db.session() as db:
            stmt = select(Candidate)
            if p.departamento:
                stmt = stmt.where(Candidate.department_key.like(f"%{normalize_key(p.departamento)}%"))
            if p.estado:
                stmt = stmt.where(Candidate.status.ilike(f"%{p.estado}%"))
            candidates = list((await db.scalars(stmt)).all())
            cv_texts: dict[int, str] = defaultdict(str)
            for t in (await db.scalars(select(CvText).where(CvText.status == "ok"))).all():
                if t.candidate_id is not None and t.text:
                    cv_texts[t.candidate_id] += "\n" + t.text
            candidates, excluded_by_cv = _apply_exclusions(p.excluir, candidates, cv_texts)
            matches = [
                Match(
                    c,
                    [
                        check_lexical(c, cv_texts.get(c.sp_id, ""), r.termino, terms_for(r.termino, r.equivalentes))
                        for r in p.requisitos
                    ],
                )
                for c in candidates
            ]
            await _semantic_pass(deps, index, db, p.requisitos, matches)
            fresh = await deps.freshness(db, "curriculums", "cv_docs")
            cv_documents = (
                await _cv_documents(db, matches, p.mostrar) if ctx.user.has(Permission.CURRICULUMS_LEER) else []
            )
        result = _result(p, matches, candidates, cv_texts, fresh, cv_documents)
        if p.excluir and isinstance(result.summary, dict):
            result.summary["excluidas_solo_por_el_texto_del_cv"] = excluded_by_cv
            result.summary["nota_exclusion"] = (
                "Se excluye a quien lo tiene en los metadatos o en su CV; «excluidas_solo_por_el_texto_del_cv» "
                "son las que no lo declaran en ninguna columna pero sí aparece en el CV."
            )
        return result

    return Tool(
        "buscar_candidatos",
        "Busca candidaturas que cumplan uno o varios requisitos (idiomas, experiencia, especialidad, formación…). "
        "Comprueba cada requisito primero en los METADATOS de la candidatura (columnas de SharePoint) y, si no "
        "está ahí, en el DOCUMENTO CV; dice dónde se cumple cada uno, con el fragmento que lo demuestra, y cuenta "
        "candidaturas y personas únicas. Pasa CADA requisito pedido y sus equivalentes. Para un perfil descrito "
        "en general, sin requisitos concretos, usa candidatos_parecidos.",
        BuscarParams,
        handler,
        permission=Permission.CURRICULUMS_LEER,
        audit_resource="curriculums",
    )


async def _cv_documents(db: Any, matches: list[Match], limit: int) -> list[dict[str, Any]]:
    """El CV de las candidaturas que se muestran (para abrirlo desde la pantalla)."""
    shown = [m for m in matches if m.meets_all or m.meets_with_possible][:limit]
    ids = [m.candidate.sp_id for m in shown]
    if not ids:
        return []
    docs = {
        candidate_id: doc_id
        for doc_id, candidate_id in (
            await db.execute(select(CvDocument.sp_id, CvDocument.candidate_id).where(CvDocument.candidate_id.in_(ids)))
        ).all()
    }
    return [
        document_entry("cv", docs[m.candidate.sp_id], f"CV de {m.candidate.name}", subtitle=m.candidate.department)
        for m in shown
        if m.candidate.sp_id in docs
    ]


def _apply_exclusions(
    excluir: list[Requisito], candidates: list[Candidate], cv_texts: dict[int, str]
) -> tuple[list[Candidate], int]:
    """Quita a quien tiene lo excluido en metadatos o CV; cuenta aparte a quien solo lo tiene en el CV."""
    if not excluir:
        return candidates, 0
    kept, by_cv_only = [], 0
    for c in candidates:
        hits = [
            check_lexical(c, cv_texts.get(c.sp_id, ""), x.termino, terms_for(x.termino, x.equivalentes))
            for x in excluir
        ]
        if any(h.where != "no" for h in hits):
            by_cv_only += all(h.where in {"cv", "no"} for h in hits)
            continue
        kept.append(c)
    return kept, by_cv_only


async def _semantic_pass(
    deps: Deps, index: CvSearchIndex, db: Any, requisitos: list[Requisito], matches: list[Match]
) -> None:
    """Para los requisitos que no aparecen literalmente, busca un fragmento de CV que trate de ello."""
    if deps.llm is None:
        return
    model = deps.settings.curriculums.embedding_model if deps.settings else "text-embedding-3-small"
    for i, r in enumerate(requisitos):
        pending = {m.candidate.sp_id: m for m in matches if m.evidence[i].where == "no"}
        # Solo quienes ya cumplen el resto: el significado sirve para completar, no para inflar resultados.
        pending = {k: m for k, m in pending.items() if all(e.where != "no" for j, e in enumerate(m.evidence) if j != i)}
        if not pending:
            continue
        vector = (await deps.llm.embed([" ".join([r.termino, *r.equivalentes])], model))[0]
        for candidate_id, (score, text) in (await index.best_per_candidate(db, vector, set(pending))).items():
            if score >= SEMANTIC_THRESHOLD:
                pending[candidate_id].evidence[i] = Evidence(r.termino, "posible", " ".join(text.split())[:220])


def _result(  # noqa: PLR0917
    p: BuscarParams,
    matches: list[Match],
    candidates: list[Candidate],
    cv_texts: dict[int, str],
    fresh: dict[str, Any],
    cv_documents: list[dict[str, Any]] | None = None,
) -> ToolResult:
    full = [m for m in matches if m.meets_all]
    possible = [m for m in matches if m.meets_with_possible and not m.meets_all]
    full.sort(
        key=lambda m: (
            -sum(e.where == "metadatos" for e in m.evidence),
            -(m.candidate.applied_on or date.min).toordinal(),
        )
    )
    shown = (full + possible)[: p.mostrar]
    per_requirement = {
        r.termino: dict(Counter(m.evidence[i].where for m in matches if m.evidence[i].where != "no"))
        for i, r in enumerate(p.requisitos)
    }
    summary: dict[str, Any] = {
        "cumplen_todos": len(full),
        "personas_unicas": len({person_identity(m.candidate) for m in full}),
        "con_indicios_en_el_cv": len(possible),
        "donde_se_cumple_cada_requisito": per_requirement,
        "candidaturas_revisadas": len(candidates),
        "con_texto_de_cv_disponible": sum(1 for c in candidates if c.sp_id in cv_texts),
        "muestra": [
            {
                **_candidate_view(m.candidate),
                "requisitos": {e.requirement: {"donde": e.where, "evidencia": e.detail} for e in m.evidence},
            }
            for m in shown
        ],
        "regla": RULE + " «posible» = el CV trata de ello pero no lo dice literalmente: preséntalo como indicio.",
        **fresh,
    }
    mark = {"metadatos": "✓ metadatos", "cv": "✓ CV", "posible": "≈ posible", "no": "—"}
    columns = ["Candidatura", "Departamento", "Estado", "Fecha", *[r.termino for r in p.requisitos]]
    rows = [
        [
            m.candidate.name,
            m.candidate.department,
            m.candidate.status,
            fmt_date(m.candidate.applied_on),
            *[f"{mark[e.where]} · {e.detail[:90]}" if e.detail else mark[e.where] for e in m.evidence],
        ]
        for m in full + possible
    ]
    return ToolResult(
        ToolStatus.OK if full or possible else ToolStatus.NOT_FOUND,
        summary,
        {**table("Candidaturas por requisitos", columns, rows), "documents": cv_documents or []},
    )


def register(registry: ToolRegistry, deps: Deps) -> None:
    from mia.modules.rrhh.curriculums.cruces import candidatos_y_plantilla  # noqa: PLC0415

    for factory in (buscar, parecidos, candidaturas, ficha_candidato, candidatos_y_plantilla):
        registry.register(factory(deps))

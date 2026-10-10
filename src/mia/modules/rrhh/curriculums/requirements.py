"""Búsqueda de candidaturas por requisitos: primero los METADATOS de la candidatura (las columnas de
CurriculosVitae) y, solo para lo que no esté ahí, los DOCUMENTOS CV asociados.

Cada requisito se comprueba por separado y se dice dónde se cumple:
  metadatos → la columna de SharePoint que lo contiene
  cv        → aparece en el texto del CV (el término o un equivalente)
  posible   → no aparece literalmente, pero un fragmento del CV trata de ello (por significado)
SEL-001 sigue vigente: es evidencia por requisito, no un ranking de idoneidad.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from mia.data import Candidate
from mia.text import normalize_key

# Equivalentes que el modelo no siempre añade (idiomas y sus niveles). El modelo añade los del dominio
# («cocina japonesa» → sushi, japanese cuisine, itamae…) a través del parámetro «equivalentes».
BUILTIN_EQUIVALENTS: dict[str, tuple[str, ...]] = {
    "ingles": ("english", "ingles", "inglés"),
    "aleman": ("german", "deutsch", "aleman", "alemán"),
    "frances": ("french", "francais", "français", "frances", "francés"),
    "italiano": ("italian", "italiano"),
    "ruso": ("russian", "ruso"),
    "arabe": ("arabic", "arabe", "árabe"),
    "portugues": ("portuguese", "portugues", "portugués"),
    "neerlandes": ("dutch", "holandes", "holandés", "neerlandes", "neerlandés"),
    "cocina": ("cocina", "cocinero", "cocinera", "chef", "kitchen", "cook", "cuisine"),
    # Cocinas nacionales: términos culinarios específicos sin el gentilicio como idioma
    "cocina_italiana": ("cocina italiana", "cucina italiana", "italian cuisine", "italian food", "italiana"),
    "cocina_japonesa": ("cocina japonesa", "japanese cuisine", "sushi", "washoku", "itamae", "ramen", "japonesa"),
    "cocina_francesa": ("cocina francesa", "french cuisine", "haute cuisine", "francesa"),
    "cocina_asiatica": ("cocina asiatica", "asian cuisine", "asian food", "asiatica", "asiática"),
}
SEMANTIC_THRESHOLD = 0.45
"""Similitud mínima (text-embedding-3-small) para considerar que un fragmento trata del requisito."""


def fold(text: str) -> str:
    """Minúsculas y sin tildes conservando la longitud (para que los fragmentos de evidencia cuadren)."""
    return "".join((unicodedata.normalize("NFKD", ch)[:1] or ch).lower() for ch in text)


def terms_for(requirement: str, equivalents: list[str] | None) -> list[str]:
    extra = BUILTIN_EQUIVALENTS.get(normalize_key(requirement), ())
    folded = (" ".join(fold(t).split()) for t in [requirement, *(equivalents or []), *extra])
    return list(dict.fromkeys(t for t in folded if t))


def _find(haystack: str, term: str) -> int:
    match = re.search(rf"(?<![a-z0-9]){re.escape(term)}", haystack)
    return match.start() if match else -1


def snippet(original: str, normalized: str, term: str, width: int = 90) -> str:
    """Fragmento alrededor de la coincidencia (sobre el texto normalizado, misma longitud aproximada)."""
    at = _find(normalized, term)
    if at < 0:
        return ""
    start, end = max(0, at - width), min(len(original), at + len(term) + width)
    return ("…" if start else "") + " ".join(original[start:end].split()) + ("…" if end < len(original) else "")


def metadata_fields(c: Candidate) -> dict[str, str]:
    base = {
        "Departamento": c.department,
        "Experiencia previa": c.experience,
        "Idiomas": c.languages,
        "Comentarios": c.comments,
        "Estado": c.status,
    }
    return {k: v for k, v in {**base, **(c.extra or {})}.items() if v}


@dataclass(slots=True)
class Evidence:
    requirement: str
    where: str  # metadatos · cv · posible · no
    detail: str = ""


@dataclass(slots=True)
class Match:
    candidate: Candidate
    evidence: list[Evidence] = field(default_factory=list)

    @property
    def meets_all(self) -> bool:
        return all(e.where in {"metadatos", "cv"} for e in self.evidence)

    @property
    def meets_with_possible(self) -> bool:
        return all(e.where != "no" for e in self.evidence)


def check_lexical(c: Candidate, cv_text: str, requirement: str, terms: list[str]) -> Evidence:
    for column, value in metadata_fields(c).items():  # 1) metadatos
        normalized = fold(value)
        for term in terms:
            if _find(normalized, term) >= 0:
                return Evidence(requirement, "metadatos", f"{column}: {snippet(value, normalized, term, 60)}")
    normalized_cv = fold(cv_text)  # 2) documento CV
    for term in terms:
        if _find(normalized_cv, term) >= 0:
            return Evidence(requirement, "cv", snippet(cv_text, normalized_cv, term))
    return Evidence(requirement, "no")

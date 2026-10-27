"""Clasificación temática determinista de noticias (por palabra clave, nunca por LLM).

La empresa/grupo (Sunset Beach Club vs. Grupo FBD) la decide la fuente de origen
(``sources.py``), no este módulo: cada fuente solo trae noticias de un bando. Aquí solo se decide
la CATEGORÍA temática dentro de ese bando.
"""

from __future__ import annotations

from mia.text import normalize_key

CATEGORY_INVERSION = "inversion_financiera"
CATEGORY_HOTELERA = "hotelera_turismo"
CATEGORY_NOMBRAMIENTOS = "nombramientos"
CATEGORY_PREMIOS = "premios_reconocimientos"
CATEGORY_GENERAL = "corporativo_general"

CATEGORY_LABELS: dict[str, str] = {
    CATEGORY_INVERSION: "Inversión / financiera",
    CATEGORY_HOTELERA: "Hotelera / turismo",
    CATEGORY_NOMBRAMIENTOS: "Nombramientos",
    CATEGORY_PREMIOS: "Premios y reconocimientos",
    CATEGORY_GENERAL: "Corporativo general",
}

# Orden deliberado: se evalúa de arriba a abajo y gana la primera que coincida, así que las
# categorías más específicas (nombramientos, premios) van antes que "hotelera" (que si no,
# se comería anuncios de nombramientos de directivos de hotel).
_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        CATEGORY_NOMBRAMIENTOS,
        (
            "nombramiento",
            "nombramientos",
            "nuevo director",
            "nueva directora",
            "nuevo presidente",
            "nueva presidenta",
            "new chairman",
            "new ceo",
            "new director",
            "appointment",
            "appointed",
            "appoints",
            "resignation",
            "dimision",
            "dimisión",
            "retirement",
            "jubilacion",
            "jubilación",
            "incorporacion de",
            "incorporación de",
        ),
    ),
    (
        CATEGORY_PREMIOS,
        ("award", "awards", "premio", "premios", "galardon", "galardón", "reconocimiento", "best hotel", "winner"),
    ),
    (
        CATEGORY_INVERSION,
        (
            "dividend",
            "dividendo",
            "shareholder",
            "accionista",
            "accionistas",
            "agm",
            "annual report",
            "informe anual",
            "buy-back",
            "buyback",
            "chairman's statement",
            "resultado financiero",
            "resultados financieros",
            "beneficio",
            "facturacion",
            "facturación",
            "revenue",
            "profit",
            "inversor",
            "inversores",
            "investor",
        ),
    ),
    (
        CATEGORY_HOTELERA,
        (
            "hotel",
            "hoteles",
            "resort",
            "turismo",
            "tourism",
            "benalmadena",
            "benalmádena",
            "costa del sol",
            "malahide",
            "acquisition",
            "adquisicion",
            "adquisición",
            "apertura",
            "renovacion",
            "renovación",
            "renovation",
            "huespedes",
            "huéspedes",
        ),
    ),
)


def classify_category(titulo: str, resumen: str = "") -> str:
    """Categoría temática por palabra clave sobre título + resumen. ``corporativo_general`` si
    no coincide ninguna — nunca se deja sin categoría."""
    text = normalize_key(f"{titulo} {resumen}")
    for category, keywords in _CATEGORY_RULES:
        if any(normalize_key(keyword) in text for keyword in keywords):
            return category
    return CATEGORY_GENERAL


def match_category_query(query: str) -> str | None:
    """Resuelve un filtro de categoría en lenguaje natural ("financiera", "premios"…) a su
    identificador interno, o ``None`` si no se reconoce ninguna (no se filtra por error)."""
    wanted = normalize_key(query)
    if not wanted:
        return None
    for category in CATEGORY_LABELS:
        if wanted in category or category.split("_")[0] in wanted:
            return category
    for category, label in CATEGORY_LABELS.items():
        if wanted in normalize_key(label):
            return category
    return None

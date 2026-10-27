"""Comparación interanual del mismo análisis económico, con periodos homogéneos.

Helper de preparación de datos para el ÚNICO motor documental: no exporta
PDF/Excel/PPTX ni consulta fuentes directamente. Conserva reglas NOM-005:
solo calcula diferencias cuando ambos periodos permiten exponer ese agregado.
"""

from __future__ import annotations

import re
from typing import Any

from mia.text import normalize_key

_MONTHS = {
    name: i
    for i, name in enumerate(
        (
            "enero",
            "febrero",
            "marzo",
            "abril",
            "mayo",
            "junio",
            "julio",
            "agosto",
            "septiembre",
            "octubre",
            "noviembre",
            "diciembre",
        ),
        1,
    )
}


def explicit_month_comparison(request: str) -> tuple[str, str] | None:
    """Resuelve dos meses explícitos o un mes común con dos ejercicios.

    Admite «agosto de 2025 y agosto de 2026» y «agosto de 2025 y 2026».
    No inventa un mes si solo se mencionan años. No interpreta dos meses
    distintos con un año ausente, ni fechas inconexas como una comparativa.
    """
    text = normalize_key(request)
    month_names = "|".join(_MONTHS)
    full_pattern = rf"\b({month_names})\s+(?:de(?:l)?\s+)?(20\d{{2}})\b"
    full = []
    for match in re.finditer(full_pattern, text):
        iso = f"{match.group(2)}-{_MONTHS[match.group(1)]:02d}"
        if iso not in full:
            full.append(iso)
    if len(full) == 2 and len(list(re.finditer(rf"\b({month_names})\b", text))) == 2:
        return tuple(sorted(full))
    if len(full) > 2:
        return None

    # Una misma referencia mensual puede regir dos años consecutivos:
    # «agosto de 2025 y 2026», «agosto 2025/2026», «agosto de los años 2025 y 2026».
    all_months = list(re.finditer(rf"\b({month_names})\b", text))
    years = list(re.finditer(r"\b20\d{2}\b", text))
    if len(all_months) != 1 or len(years) != 2:
        return None
    if years[0].group() == years[1].group():
        return None
    connector = text[years[0].end() : years[1].start()]
    valid_connector = bool(
        re.fullmatch(r"\s*(?:y|e|vs|versus|contra|con|frente a|respecto a)\s*(?:de(?:l)?\s+)?", connector)
    )
    # normalize_key quita «/» y «-»; distinguir "2025/2026" de dos años
    # meramente yuxtapuestos para no deducir una comparativa inexistente.
    if not valid_connector and not connector.strip():
        valid_connector = bool(re.search(r"\b20\d{2}\s*[/\-]\s*20\d{2}\b", str(request)))
    if not valid_connector:
        return None
    month = all_months[0]
    # Dos años deben estar vinculados al mes; si el mes está lejos o
    # acompañado de otra referencia temporal, no extrapolamos.
    before = text[month.end() : years[0].start()] if month.end() <= years[0].start() else ""
    after = text[years[1].end() : month.start()] if years[1].end() <= month.start() else ""
    before_ok = bool(re.fullmatch(r"\s*(?:de(?:l)?\s+)?(?:(?:los\s+)?anos\s+)?", before))
    after_ok = bool(re.fullmatch(r"\s*(?:en|de(?:l)?|para(?:\s+el\s+mes\s+de)?)\s+", after))
    if not before_ok and not after_ok:
        return None
    return tuple(sorted(f"{y.group()}-{_MONTHS[month.group(1)]:02d}" for y in years))


LAST_PAYROLL_COMPARISON = "ultima_comparativa_nominas_solicitada"


def is_export_followup(text: str) -> bool:
    """Una referencia a exportar el informe ya pedido, sin otro periodo explícito.

    No interpreta peticiones de métricas nuevas ni fechas distintas. El motor
    comprobará después que el contexto conservado es salarial y autorizado.
    """
    norm = normalize_key(text)
    if re.search(r"\b20\d{2}\b", norm):
        return False
    if any(re.search(rf"\b{name}\b", norm) for name in _MONTHS):
        return False
    export = any(
        re.search(rf"\b{word}\b", norm)
        for word in ("pdf", "excel", "xlsx", "pptx", "powerpoint", "exporta", "exportar", "descarga", "descargar")
    )
    reference = any(
        re.search(rf"\b{word}\b", norm)
        for word in (
            "informe",
            "comparativa",
            "comparacion",
            "anterior",
            "resultado",
            "tabla",
            "ese",
            "esa",
            "esto",
            "esta",
        )
    )
    # Un informe nuevo con descripción larga no debe reaprovechar automáticamente
    # una comparativa salarial anterior. El seguimiento es una referencia breve.
    if len(norm.split()) > 14:
        return False
    generic_previous = bool(
        re.fullmatch(
            r"(?:ahora )?(?:genera|generame|haz|prepara|pasame|dame|quiero|exporta) (?:el |un |la )?(?:informe )?(?:en )?(?:pdf|excel|xlsx|pptx|powerpoint)(?: del informe)?",
            norm,
        )
    )
    return export and (reference or generic_previous)


def remembered_comparison(state: dict, message: str) -> tuple[tuple[str, str], set[str]] | None:
    """Resuelve un seguimiento explícito contra metadatos sin cifras personales."""
    if not is_export_followup(message):
        return None
    item = state.get(LAST_PAYROLL_COMPARISON)
    if not isinstance(item, dict):
        return None
    periods = item.get("periodos")
    fields = item.get("campos")
    if (
        not isinstance(periods, list)
        or len(periods) != 2
        or not all(isinstance(p, str) and re.fullmatch(r"20\d{2}-(?:0[1-9]|1[0-2])", p) for p in periods)
        or not isinstance(fields, list)
        or not fields
        or not all(isinstance(f, str) for f in fields)
    ):
        return None
    return tuple(sorted(periods)), set(fields)


def merge_payroll_comparison(
    first: dict[str, Any],
    second: dict[str, Any],
    periods: tuple[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Une resultados ya autorizados sin reconstruir datos de empleados.

    No inventa ceros para departamentos ausentes ni compara periodos con
    importes ocultos; la variación se calcula solo sobre intersección visible.
    """
    a, b = first, second
    if a.get("concepto_economico") != b.get("concepto_economico"):
        raise ValueError("Los dos periodos deben calcular el mismo concepto económico")
    if a.get("poblacion") != b.get("poblacion"):
        raise ValueError("Las dos consultas deben usar el mismo filtro de población")
    for summary, period in ((a, periods[0]), (b, periods[1])):
        if summary.get("meses_analizados") != [period]:
            raise ValueError(f"El análisis no corresponde exactamente al mes {period}")
        if summary.get("meses_sin_datos") or summary.get("meses_con_datos") != [period]:
            raise ValueError(f"Faltan datos para el periodo {period}; no se fabrica una comparación")
    da = a.get("por_departamento") or {}
    db = b.get("por_departamento") or {}
    names = sorted(set(da) | set(db))
    included, excluded = [], []
    for name in names:
        left = da.get(name, {})
        right = db.get(name, {})
        lv = left.get("total")
        rv = right.get("total")
        if not isinstance(lv, int | float) or not isinstance(rv, int | float):
            excluded.append(name)
            continue
        included.append((name, float(lv), float(rv), left.get("personas_con_nomina"), right.get("personas_con_nomina")))
    if not included:
        raise ValueError("No hay departamentos con datos visibles en ambos periodos")
    included.sort(key=lambda r: -r[2])
    left_sum = round(sum(item[1] for item in included), 2)
    right_sum = round(sum(item[2] for item in included), 2)
    difference = round(right_sum - left_sum, 2)
    pct = round(difference / left_sum * 100, 2) if left_sum else None
    rows = []
    for name, lv, rv, left_people, right_people in included:
        rows.append(
            [
                name,
                round(lv, 2),
                round(rv, 2),
                round(rv - lv, 2),
                round((rv - lv) / lv * 100, 2) if lv else None,
                left_people,
                right_people,
            ]
        )
    rows.append(["TOTAL comparable", left_sum, right_sum, difference, pct, None, None])
    warnings = [
        "La comparación considera exclusivamente departamentos con importes visibles en AMBOS periodos; "
        "no representa necesariamente el gasto total de toda la empresa (protección NOM-005).",
        "Departamento asignado según la ficha disponible actualmente; no se ha verificado un histórico "
        "de adscripciones. La composición de plantilla puede variar entre periodos.",
    ]
    if excluded:
        warnings.append(
            f"{len(excluded)} departamentos sin datos comparables en ambos periodos "
            "(ausentes, incompletos u ocultos por privacidad): no se calculan diferencias para ellos."
        )
    if any(x[3] != x[4] for x in included):
        warnings.append(
            "El número de personas con nómina difiere en uno o más departamentos; "
            "la variación mezcla cambios de coste y de tamaño de plantilla."
        )
    for source in (a, b):
        for warning in source.get("advertencias") or []:
            if isinstance(warning, str) and warning not in warnings:
                warnings.append(warning)
    label_a, label_b = periods
    source_name = a["concepto_economico"]

    def euro(value: float) -> str:
        return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"

    presentation = {
        "type": "table",
        "title": f"Comparativa {source_name} por departamento · {label_a} / {label_b}",
        "columns": [
            "Departamento",
            label_a + " (€)",
            label_b + " (€)",
            "Variación (€)",
            "Variación (%)",
            "Personas " + label_a,
            "Personas " + label_b,
        ],
        "rows": rows,
        "kpis": [
            {"label": f"Total comparable {label_a}", "value": euro(left_sum)},
            {"label": f"Total comparable {label_b}", "value": euro(right_sum)},
            {"label": "Variación (€)", "value": euro(difference)},
            {
                "label": "Variación (%)",
                "value": f"{pct:.2f}%".replace(".", ",") if pct is not None else "No calculable",
            },
        ],
        "charts": [
            {
                "type": "grouped_bar",
                "title": "Comparativa por departamento",
                "labels": [x[0] for x in included],
                "series": [
                    {"name": label_a, "values": [x[1] for x in included]},
                    {"name": label_b, "values": [x[2] for x in included]},
                ],
            },
        ],
    }
    summary = {
        "periodo_interpretado": f"{label_a} vs {label_b}",
        "concepto_economico": source_name,
        "poblacion": a.get("poblacion"),
        "meses_analizados": list(periods),
        "comparacion_homogenea_en_concepto": True,
        "departamentos_comparables": len(included),
        "total_comparable_anterior": left_sum,
        "total_comparable_actual": right_sum,
        "variacion_eur": difference,
        "variacion_pct": pct,
        "advertencias": warnings,
    }
    return presentation, summary

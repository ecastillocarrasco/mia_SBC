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


_THIS_YEAR_HINTS = ("este ano", "el ano actual", "ano actual", "ano en curso")
_LAST_YEAR_HINTS = ("ano pasado", "el ano anterior", "ano anterior", "ultimo ano", "el ultimo ano")


def relative_year_comparison(request: str) -> tuple[str, str] | None:
    """"Este año y el año pasado", "año actual comparado con el anterior"... — a diferencia de
    ``explicit_month_comparison`` (un mes concreto en dos años, p. ej. "agosto 2025 y 2026"), esto
    compara los DOS AÑOS COMPLETOS (el actual, hasta hoy; el pasado, completo).

    Devuelve las expresiones literales ("año pasado", "este año") que ``period_engine.resolve()``
    YA sabe interpretar (ver mia/query/period.py) — nunca fechas calculadas aquí, para no duplicar
    esa resolución en dos sitios y arriesgar que diverjan.

    Exige que AMBAS referencias (este año Y el año pasado) aparezcan explícitas en la petición,
    igual de estricto que ``explicit_month_comparison``: no interpreta una mención suelta de "el
    año pasado" (sin comparar con nada) como si pidiera una comparativa."""
    text = normalize_key(request)
    has_this_year = any(re.search(rf"\b{re.escape(hint)}\b", text) for hint in _THIS_YEAR_HINTS)
    has_last_year = any(re.search(rf"\b{re.escape(hint)}\b", text) for hint in _LAST_YEAR_HINTS)
    if has_this_year and has_last_year:
        return ("año pasado", "este año")
    return None


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
    single_month = re.compile(r"^20\d{2}-(?:0[1-9]|1[0-2])$")
    for summary, period in ((a, periods[0]), (b, periods[1])):
        analyzed = summary.get("meses_analizados")
        if single_month.fullmatch(period):
            # Comportamiento original, sin tocar: un mes concreto ("2026-08") debe analizar
            # EXACTAMENTE ese mes, ni uno distinto ni un rango -- si no coincide, el resultado no
            # corresponde a lo pedido (p. ej. una ejecución de julio reutilizada para "agosto").
            if analyzed != [period]:
                raise ValueError(f"El análisis no corresponde exactamente al mes {period}")
        elif not isinstance(analyzed, list) or not analyzed:
            # Periodo multi-mes ("año pasado"/"este año", vía period_engine): no hay un único mes
            # literal contra el que comparar el string del periodo, así que no se repite esa
            # comprobación -- solo que de verdad se haya analizado algo.
            raise ValueError(f"El análisis no corresponde al periodo {period}")
        if summary.get("meses_sin_datos") or summary.get("meses_con_datos") != analyzed:
            raise ValueError(f"Faltan datos para completar el periodo {period}; no se fabrica una comparación")
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


def _eur(value: float) -> str:
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def _merge_bucket_comparison(
    a_bucket: dict[str, dict[str, Any]],
    b_bucket: dict[str, dict[str, Any]],
    label_a: str,
    label_b: str,
    row_label: str,
) -> tuple[dict[str, Any], list[tuple[str, float, float]], list[str]] | None:
    """Fusiona un desglose (por departamento o por empresa) de dos periodos en una tabla
    comparativa; ``None`` si no hay ningún nombre con importe en ambos periodos (nunca se compara
    una lista vacía). Devuelve (tabla, [(nombre, importe_a, importe_b)...], avisos)."""
    names = sorted(set(a_bucket) | set(b_bucket))
    included: list[tuple[str, float, float, float, float]] = []
    excluded: list[str] = []
    for name in names:
        left = a_bucket.get(name, {})
        right = b_bucket.get(name, {})
        lv, rv = left.get("importe"), right.get("importe")
        if not isinstance(lv, int | float) or not isinstance(rv, int | float):
            excluded.append(name)
            continue
        included.append((name, float(lv), float(rv), float(left.get("horas") or 0), float(right.get("horas") or 0)))
    if not included:
        return None
    included.sort(key=lambda r: -r[2])
    rows = [
        [
            name, round(lv, 2), round(rv, 2), round(rv - lv, 2),
            round((rv - lv) / lv * 100, 2) if lv else None, round(lh, 2), round(rh, 2),
        ]
        for name, lv, rv, lh, rh in included
    ]
    table = {
        "type": "table",
        "title": f"Comparativa de trabajo temporal por {row_label.lower()} · {label_a} / {label_b}",
        "columns": [
            row_label, label_a + " (€)", label_b + " (€)", "Variación (€)", "Variación (%)",
            "Horas " + label_a, "Horas " + label_b,
        ],
        "rows": rows,
    }
    warnings = (
        [f"{len(excluded)} {row_label.lower()}(s) sin datos comparables en ambos periodos."] if excluded else []
    )
    return table, [(name, lv, rv) for name, lv, rv, *_ in included], warnings


def merge_trabajo_temporal_comparison(
    first: dict[str, Any],
    second: dict[str, Any],
    periods: tuple[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Comparación interanual de gasto en trabajo temporal (boletines_tt), mismo patrón que
    ``merge_payroll_comparison`` pero sin controles NOM-005 (trabajo temporal no agrega por grupos
    protegidos: cada boletín ya es un importe individual visible, no hay umbral que proteger)."""
    a, b = first, second
    label_a, label_b = periods
    dept = _merge_bucket_comparison(a.get("por_departamento") or {}, b.get("por_departamento") or {}, label_a, label_b, "Departamento")
    company = _merge_bucket_comparison(a.get("por_empresa") or {}, b.get("por_empresa") or {}, label_a, label_b, "Empresa")
    if dept is None and company is None:
        raise ValueError("No hay departamentos ni empresas con datos comparables en ambos periodos")
    warnings: list[str] = []
    tables: list[dict[str, Any]] = []
    charts: list[dict[str, Any]] = []
    main_table: dict[str, Any] | None = None
    total_a = total_b = 0.0
    for merged in (dept, company):
        if merged is None:
            continue
        table, rows_pairs, table_warnings = merged
        warnings.extend(table_warnings)
        if main_table is None:
            main_table = table
            total_a = round(sum(r[1] for r in rows_pairs), 2)
            total_b = round(sum(r[2] for r in rows_pairs), 2)
        else:
            tables.append(table)
        charts.append({
            "type": "grouped_bar",
            "title": table["title"],
            "labels": [r[0] for r in rows_pairs],
            "series": [
                {"name": label_a, "values": [r[1] for r in rows_pairs]},
                {"name": label_b, "values": [r[2] for r in rows_pairs]},
            ],
        })
    assert main_table is not None  # noqa: S101 — garantizado por el `if dept is None and company is None` de arriba
    difference = round(total_b - total_a, 2)
    pct = round(difference / total_a * 100, 2) if total_a else None
    main_table["kpis"] = [
        {"label": f"Importe total {label_a}", "value": _eur(total_a)},
        {"label": f"Importe total {label_b}", "value": _eur(total_b)},
        {"label": "Variación (€)", "value": _eur(difference)},
        {"label": "Variación (%)", "value": f"{pct:.2f}%".replace(".", ",") if pct is not None else "No calculable"},
    ]
    main_table["tables"] = tables
    main_table["charts"] = charts
    summary = {
        "periodo_interpretado": f"{label_a} vs {label_b}",
        "importe_total_anterior": total_a,
        "importe_total_actual": total_b,
        "variacion_eur": difference,
        "variacion_pct": pct,
        "advertencias": warnings or None,
    }
    return main_table, summary

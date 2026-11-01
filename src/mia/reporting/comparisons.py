"""Comparación interanual del mismo análisis económico, con periodos homogéneos.

Helper de preparación de datos para el ÚNICO motor documental: no exporta
PDF/Excel/PPTX ni consulta fuentes directamente. Conserva reglas NOM-005:
solo calcula diferencias cuando ambos periodos permiten exponer ese agregado.
"""

from __future__ import annotations

import re
from datetime import date
from itertools import pairwise
from typing import Any

from mia.query.period import period_engine
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


_YEAR_CONNECTOR_WORDS = r"(?:y|e|vs\.?|versus|contra|con|frente a|respecto a)"
_YEAR_CONNECTOR = re.compile(
    rf"^(?:[/\-]|,|{_YEAR_CONNECTOR_WORDS}|,\s*{_YEAR_CONNECTOR_WORDS})(?:\s+de(?:l)?)?$", re.IGNORECASE
)


def _years_well_connected(request: str, years_in_order: list[str]) -> bool:
    """Para N (≥2) años EN ORDEN DE APARICIÓN: cada par consecutivo debe estar unido por una coma,
    una barra/guion o un conector válido («2024, 2025 y 2026», «2025/2026») — generalizado del
    caso de 2 años, no relajado: años sueltos sin ningún separador real siguen sin ser una
    comparativa. Opera sobre ``request`` SIN normalizar: ``normalize_key`` colapsa la coma a un
    espacio, con lo que "2024, 2025" y "2024 2025" (dos años sueltos, sin relación) dejarían de
    poder distinguirse si se buscara aquí sobre el texto ya normalizado."""
    found = list(re.finditer(r"\b20\d{2}\b", request))
    if [m.group() for m in found] != years_in_order:
        return False  # el orden/los valores no cuadran con lo ya detectado sobre el texto normalizado
    for left, right in pairwise(found):
        connector = request[left.end() : right.start()].strip()
        if not connector or not _YEAR_CONNECTOR.fullmatch(connector):
            return False
    return True


def explicit_month_comparison(request: str) -> tuple[str, ...] | None:
    """Resuelve dos meses explícitos (posiblemente distintos) o un mes común con N (≥2) ejercicios.

    Admite «agosto de 2025 y agosto de 2026», «agosto de 2025 y 2026» y, generalizado a más de
    dos años con el MISMO mes, «agosto de 2024, 2025 y 2026». Deliberadamente NO generaliza a 3+
    pares "mes año" explícitos con meses distintos entre sí (p. ej. "agosto 2025, septiembre 2026
    y octubre 2026"): mezclar meses Y años distintos a la vez es intrínsecamente ambiguo (¿es una
    comparativa real o una narración secuencial de varios meses seguidos?) — solo el caso de
    EXACTAMENTE 2 pares con meses distintos es lo bastante inequívoco para aceptarse sin preguntar.
    No inventa un mes si solo se mencionan años. No interpreta meses
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
    all_month_mentions = list(re.finditer(rf"\b({month_names})\b", text))
    if len(full) == 2 and len(all_month_mentions) == 2:
        return tuple(sorted(full))
    if len(full) > 2:
        return None

    # Una misma referencia mensual puede regir varios ejercicios:
    # «agosto de 2025 y 2026», «agosto 2025/2026», «agosto de los años 2024, 2025 y 2026».
    years = list(re.finditer(r"\b20\d{2}\b", text))
    distinct_years = {y.group() for y in years}
    if len(all_month_mentions) != 1 or len(distinct_years) < 2 or len(distinct_years) != len(years):
        return None
    if not _years_well_connected(str(request), [y.group() for y in years]):
        return None
    month = all_month_mentions[0]
    # Los años deben estar vinculados al mes; si el mes está lejos o
    # acompañado de otra referencia temporal, no extrapolamos.
    before = text[month.end() : years[0].start()] if month.end() <= years[0].start() else ""
    after = text[years[-1].end() : month.start()] if years[-1].end() <= month.start() else ""
    before_ok = bool(re.fullmatch(r"\s*(?:de(?:l)?\s+)?(?:(?:los\s+)?anos\s+)?", before))
    after_ok = bool(re.fullmatch(r"\s*(?:en|de(?:l)?|para(?:\s+el\s+mes\s+de)?)\s+", after))
    if not before_ok and not after_ok:
        return None
    return tuple(sorted(f"{y.group()}-{_MONTHS[month.group(1)]:02d}" for y in years))


def explicit_year_list_comparison(request: str) -> tuple[str, ...] | None:
    """"Compara 2024, 2025 y 2026" / "gastos entre 2023 y 2026" — dos o más AÑOS COMPLETOS
    explícitos, sin ningún mes de por medio (eso es ``explicit_month_comparison``). Cada año se
    resuelve igual que "este año"/"año pasado" vía ``period_engine`` (el actual, hasta hoy; los
    demás, completos) — nunca fechas calculadas aquí."""
    text = normalize_key(request)
    month_names = "|".join(_MONTHS)
    if re.search(rf"\b({month_names})\b", text):
        return None  # un mes de por medio es terreno de explicit_month_comparison
    years = list(re.finditer(r"\b20\d{2}\b", text))
    distinct_years = {y.group() for y in years}
    if len(distinct_years) < 2 or len(distinct_years) != len(years):
        return None
    if not _years_well_connected(str(request), [y.group() for y in years]):
        return None
    return tuple(sorted(distinct_years))


_THIS_YEAR_HINTS = ("este ano", "el ano actual", "ano actual", "ano en curso")
_LAST_YEAR_HINTS = ("ano pasado", "el ano anterior", "ano anterior", "ultimo ano", "el ultimo ano")


def relative_year_comparison(request: str) -> tuple[str, str] | None:
    """ "Este año y el año pasado", "año actual comparado con el anterior"... — a diferencia de
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
            (
                "(?:ahora )?(?:genera|generame|haz|prepara|pasame|dame|quiero|expo"
                "rta) (?:el |un |la )?(?:informe )?(?:en "
                ")?(?:pdf|excel|xlsx|pptx|powerpoint)(?: del informe)?"
            ),
            norm,
        )
    )
    return export and (reference or generic_previous)


def remembered_comparison(state: dict[str, Any], message: str) -> tuple[tuple[str, str], set[str]] | None:
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


def _validate_comparison_periods(
    results: list[dict[str, Any]], periods: tuple[str, ...], *, today: date | None
) -> None:
    single_month = re.compile(r"^20\d{2}-(?:0[1-9]|1[0-2])$")
    for summary, period in zip(results, periods, strict=True):
        analyzed = summary.get("meses_analizados")
        if single_month.fullmatch(period):
            # Comportamiento original, sin tocar: un mes concreto ("2026-08") debe analizar
            # EXACTAMENTE ese mes, ni uno distinto ni un rango -- si no coincide, el resultado no
            # corresponde a lo pedido (p. ej. una ejecución de julio reutilizada para "agosto").
            if analyzed != [period]:
                raise ValueError(f"El análisis no corresponde exactamente al mes {period}")
        else:
            resolved = period_engine.resolve(period, today=today)
            if resolved is None:
                raise ValueError("No se puede verificar el periodo de la comparación")
            start = resolved.start.year * 12 + resolved.start.month - 1
            end = resolved.end.year * 12 + resolved.end.month - 1
            expected = [f"{month // 12:04d}-{month % 12 + 1:02d}" for month in range(start, end + 1)]
            if analyzed != expected:
                raise ValueError("Los meses analizados no corresponden exactamente al periodo solicitado")
        if summary.get("meses_sin_datos") or summary.get("meses_con_datos") != analyzed:
            raise ValueError(f"Faltan datos para completar el periodo {period}; no se fabrica una comparación")


def merge_payroll_comparison(
    results: list[dict[str, Any]],
    periods: tuple[str, ...],
    *,
    today: date | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Une N (≥2) resultados ya autorizados sin reconstruir datos de empleados: "2024, 2025 y
    2026" se trata igual que "este año y el año pasado", solo con más columnas. La variación
    mostrada es siempre PRIMER periodo → ÚLTIMO (no la suma de variaciones intermedias).

    No inventa ceros para departamentos ausentes ni compara periodos con
    importes ocultos; la variación se calcula solo sobre intersección visible.
    """
    if len(periods) < 2 or len(results) != len(periods):
        raise ValueError("Hacen falta al menos dos periodos, uno por cada resultado a comparar")
    concepts = {r.get("concepto_economico") for r in results}
    if len(concepts) != 1:
        raise ValueError("Todos los periodos deben calcular el mismo concepto económico")
    poblaciones = {r.get("poblacion") for r in results}
    if len(poblaciones) != 1:
        raise ValueError("Todas las consultas deben usar el mismo filtro de población")
    _validate_comparison_periods(results, periods, today=today)
    buckets = [r.get("por_departamento") or {} for r in results]
    names = sorted(set().union(*buckets))
    included: list[tuple[str, list[float], list[Any]]] = []
    excluded: list[str] = []
    for name in names:
        entries = [b.get(name, {}) for b in buckets]
        values = [e.get("total") for e in entries]
        if not all(isinstance(v, int | float) for v in values):
            excluded.append(name)
            continue
        included.append((name, [float(v) for v in values], [e.get("personas_con_nomina") for e in entries]))
    if not included:
        raise ValueError("No hay departamentos con datos visibles en todos los periodos")
    included.sort(key=lambda r: -r[1][-1])
    totals = [round(sum(item[1][i] for item in included), 2) for i in range(len(periods))]
    difference = round(totals[-1] - totals[0], 2)
    pct = round(difference / totals[0] * 100, 2) if totals[0] else None
    rows = []
    for name, values, people in included:
        row_diff = round(values[-1] - values[0], 2)
        row_pct = round((values[-1] - values[0]) / values[0] * 100, 2) if values[0] else None
        rows.append([name, *(round(v, 2) for v in values), row_diff, row_pct, *people])
    rows.append(["TOTAL comparable", *totals, difference, pct, *([None] * len(periods))])
    warnings = [
        f"La comparación considera exclusivamente departamentos con importes visibles en los {len(periods)} "
        "periodos; no representa necesariamente el gasto total de toda la empresa (protección NOM-005).",
        "Departamento asignado según la ficha disponible actualmente; no se ha verificado un histórico "
        "de adscripciones. La composición de plantilla puede variar entre periodos.",
    ]
    if excluded:
        warnings.append(
            f"{len(excluded)} departamentos sin datos comparables en todos los periodos "
            "(ausentes, incompletos u ocultos por privacidad): no se calculan diferencias para ellos."
        )
    if any(len({p for p in people if p is not None}) > 1 for _, _, people in included):
        warnings.append(
            "El número de personas con nómina difiere entre periodos en uno o más departamentos; "
            "la variación mezcla cambios de coste y de tamaño de plantilla."
        )
    for source in results:
        for warning in source.get("advertencias") or []:
            if isinstance(warning, str) and warning not in warnings:
                warnings.append(warning)
    source_name = results[0]["concepto_economico"]

    def euro(value: float) -> str:
        return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"

    presentation = {
        "type": "table",
        "title": f"Comparativa {source_name} por departamento · {' / '.join(periods)}",
        "columns": [
            "Departamento",
            *(label + " (€)" for label in periods),
            "Variación (€)",
            "Variación (%)",
            *("Personas " + label for label in periods),
        ],
        "rows": rows,
        "kpis": [
            *(
                {"label": f"Total comparable {label}", "value": euro(totals[i])}
                for i, label in enumerate(periods)
            ),
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
                    {"name": label, "values": [x[1][i] for x in included]} for i, label in enumerate(periods)
                ],
            },
        ],
    }
    summary = {
        "periodo_interpretado": " vs ".join(periods),
        "concepto_economico": source_name,
        "poblacion": results[0].get("poblacion"),
        "meses_analizados": list(periods),
        "comparacion_homogenea_en_concepto": True,
        "departamentos_comparables": len(included),
        "totales_por_periodo": dict(zip(periods, totals, strict=True)),
        "total_comparable_anterior": totals[0],
        "total_comparable_actual": totals[-1],
        "variacion_eur": difference,
        "variacion_pct": pct,
        "advertencias": warnings,
    }
    return presentation, summary


def _eur(value: float) -> str:
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def _merge_bucket_comparison(
    buckets: list[dict[str, dict[str, Any]]],
    periods: tuple[str, ...],
    row_label: str,
) -> tuple[dict[str, Any], list[tuple[str, list[float]]], list[str]] | None:
    """Fusiona un desglose (por departamento o por empresa) de N (≥2) periodos en una tabla
    comparativa; ``None`` si no hay ningún nombre con importe en TODOS los periodos (nunca se
    compara una lista vacía). Devuelve (tabla, [(nombre, [importe_periodo_1, ...])...], avisos)."""
    names = sorted(set().union(*buckets))
    included: list[tuple[str, list[float], list[float]]] = []
    excluded: list[str] = []
    for name in names:
        entries = [b.get(name, {}) for b in buckets]
        importes = [v for v in (e.get("importe") for e in entries) if isinstance(v, int | float)]
        if len(importes) != len(entries):
            excluded.append(name)
            continue
        horas = [float(e.get("horas") or 0) for e in entries]
        included.append((name, [float(v) for v in importes], horas))
    if not included:
        return None
    included.sort(key=lambda r: -r[1][-1])
    rows = [
        [
            name,
            *(round(v, 2) for v in importes),
            round(importes[-1] - importes[0], 2),
            round((importes[-1] - importes[0]) / importes[0] * 100, 2) if importes[0] else None,
            *(round(h, 2) for h in horas),
        ]
        for name, importes, horas in included
    ]
    table = {
        "type": "table",
        "title": f"Comparativa de trabajo temporal por {row_label.lower()} · {' / '.join(periods)}",
        "columns": [
            row_label,
            *(label + " (€)" for label in periods),
            "Variación (€)",
            "Variación (%)",
            *("Horas " + label for label in periods),
        ],
        "rows": rows,
    }
    warnings = (
        [f"{len(excluded)} {row_label.lower()}(s) sin datos comparables en todos los periodos."] if excluded else []
    )
    return table, [(name, importes) for name, importes, _ in included], warnings


def merge_trabajo_temporal_comparison(
    results: list[dict[str, Any]],
    periods: tuple[str, ...],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Comparación de gasto en trabajo temporal (boletines_tt) entre N (≥2) periodos, mismo patrón
    que ``merge_payroll_comparison`` pero sin controles NOM-005 (trabajo temporal no agrega por
    grupos protegidos: cada boletín ya es un importe individual visible, no hay umbral que
    proteger). La variación mostrada es siempre PRIMER periodo → ÚLTIMO."""
    if len(periods) < 2 or len(results) != len(periods):
        raise ValueError("Hacen falta al menos dos periodos, uno por cada resultado a comparar")
    dept = _merge_bucket_comparison([r.get("por_departamento") or {} for r in results], periods, "Departamento")
    company = _merge_bucket_comparison([r.get("por_empresa") or {} for r in results], periods, "Empresa")
    if dept is None and company is None:
        raise ValueError("No hay departamentos ni empresas con datos comparables en todos los periodos")
    warnings: list[str] = []
    tables: list[dict[str, Any]] = []
    charts: list[dict[str, Any]] = []
    main_table: dict[str, Any] | None = None
    totals = [0.0] * len(periods)
    for merged in (dept, company):
        if merged is None:
            continue
        table, rows_pairs, table_warnings = merged
        warnings.extend(table_warnings)
        if main_table is None:
            main_table = table
            totals = [round(sum(r[1][i] for r in rows_pairs), 2) for i in range(len(periods))]
        else:
            tables.append(table)
        charts.append(
            {
                "type": "grouped_bar",
                "title": table["title"],
                "labels": [r[0] for r in rows_pairs],
                "series": [
                    {"name": label, "values": [r[1][i] for r in rows_pairs]} for i, label in enumerate(periods)
                ],
            }
        )
    assert main_table is not None  # noqa: S101 — garantizado por el `if dept is None and company is None` de arriba
    difference = round(totals[-1] - totals[0], 2)
    pct = round(difference / totals[0] * 100, 2) if totals[0] else None
    main_table["kpis"] = [
        *(
            {"label": f"Importe total {label}", "value": _eur(totals[i])}
            for i, label in enumerate(periods)
        ),
        {"label": "Variación (€)", "value": _eur(difference)},
        {"label": "Variación (%)", "value": f"{pct:.2f}%".replace(".", ",") if pct is not None else "No calculable"},
    ]
    main_table["tables"] = tables
    main_table["charts"] = charts
    summary = {
        "periodo_interpretado": " vs ".join(periods),
        "totales_por_periodo": dict(zip(periods, totals, strict=True)),
        "importe_total_anterior": totals[0],
        "importe_total_actual": totals[-1],
        "variacion_eur": difference,
        "variacion_pct": pct,
        "advertencias": warnings or None,
    }
    return main_table, summary

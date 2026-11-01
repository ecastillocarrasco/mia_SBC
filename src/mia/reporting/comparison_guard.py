"""Local evidence checks for conclusions drawn from incomplete payroll periods."""

from __future__ import annotations

from mia.conversation.tools import ToolExecution, ToolStatus


def unavailable_payroll_sources(executions: list[ToolExecution]) -> str | None:
    """Availability is a source contract, independent of which metadata tool was selected."""
    fields = {"nominas_periodo": "con_nomina", "anomalias_nominas": "nominas_en_el_periodo"}
    periods = []
    for execution in executions:
        field = fields.get(execution.call.name)
        summary = execution.result.summary
        if field and execution.result.status is ToolStatus.OK and isinstance(summary, dict):
            value = summary.get(field)
            if type(value) is int and value == 0 and isinstance(summary.get("periodo"), str):
                periods.append(summary["periodo"])
    if not periods:
        return None
    return "\n".join(
        f"No hay nóminas vinculadas a la población consultada en {period}. "
        "No se pueden calcular importes ni completar un análisis salarial de ese periodo con esta fuente."
        for period in dict.fromkeys(periods)
    )


def incomplete_payroll_comparison(executions: list[ToolExecution]) -> str | None:
    """Do not certify a change when either compared source lacks requested months.

    Tables remain available. The decision uses source coverage, never a model's
    description of that coverage, and discloses no additional financial values.
    """
    sources = [
        execution.result.summary
        for execution in executions
        if execution.call.name == "analisis_economico_nominas" and execution.result.status is ToolStatus.OK
    ]
    if len(sources) < 2 or not any(source.get("meses_sin_datos") for source in sources):
        return None
    coverage = []
    for source in sources:
        available = ", ".join(source.get("meses_con_datos") or []) or "ninguno"
        missing = ", ".join(source.get("meses_sin_datos") or []) or "ninguno"
        coverage.append(
            f"Periodo {source.get('periodo_interpretado', 'consultado')}: "
            f"meses con datos: {available}; meses sin datos: {missing}."
        )
    return "\n".join(
        [
            "La comparación es parcial: faltan meses solicitados en al menos uno de los periodos.",
            *dict.fromkeys(coverage),
            "Los totales de las tablas solo representan los datos disponibles. "
            "No se puede certificar una subida o bajada del coste entre los periodos completos. "
            "Para una conclusión comparable hay que consultar los mismos meses con cobertura en ambos periodos "
            "o completar los datos ausentes.",
        ]
    )

"""Regresiones para la exportación comparativa sin tabla histórica activa."""

import asyncio
from datetime import datetime
from types import SimpleNamespace

from mia.modules.rrhh.informes import tools as report_tools
from mia.reporting.comparisons import (
    LAST_PAYROLL_COMPARISON,
    is_export_followup,
    remembered_comparison,
)


def test_followup_does_not_need_both_tables_active():
    context = {LAST_PAYROLL_COMPARISON: {"periodos": ["2025-08", "2026-08"], "campos": ["coste_empresa"]}}
    assert remembered_comparison(context, "Ahora genera el PDF de esa comparativa") == (
        ("2025-08", "2026-08"),
        {"coste_empresa"},
    )
    assert remembered_comparison(context, "Exporta agosto de 2024") is None
    assert remembered_comparison({}, "Exporta esa comparativa") is None
    assert is_export_followup("genera el PDF del informe anterior")


def test_exporter_routes_explicit_and_followup_comparisons_without_active_results(monkeypatch):
    calls = []

    async def mock_comparison(_deps, _ctx, periods, **kwargs):
        calls.append((periods, kwargs["concepto"]))
        return SimpleNamespace(status="ok")

    def fake_plan(message, **_):
        payroll = "nominas" in message or "costes" in message
        metrics = [SimpleNamespace(field=SimpleNamespace(domain="payroll", name="coste_empresa"))] if payroll else []
        return SimpleNamespace(metrics=metrics, compare=False, period=None)

    monkeypatch.setattr(report_tools, "planner", SimpleNamespace(plan=fake_plan))
    monkeypatch.setattr(report_tools, "_run_economic_comparison", mock_comparison)
    tool = report_tools.generar(object())
    assert tool.timeout_seconds >= 560  # dos consultas históricas independientes
    params = SimpleNamespace(
        formato="pdf", titulo=None, incluir_detalle=True, incluir_grafico=True, incluir_narrativa=False
    )
    now = datetime(2026, 10, 14)
    direct = SimpleNamespace(
        user_message="PDF de costes de nominas agosto 2025 y 2026", now=now, user=object(), session_state={}
    )
    followup = SimpleNamespace(
        user_message="Ahora genera el PDF de esa comparativa",
        now=now,
        user=object(),
        session_state={LAST_PAYROLL_COMPARISON: {"periodos": ["2025-08", "2026-08"], "campos": ["coste_empresa"]}},
    )
    assert asyncio.run(tool.handler(params, direct)).status == "ok"
    assert asyncio.run(tool.handler(params, followup)).status == "ok"
    contextual = SimpleNamespace(
        user_message="PDF de la comparativa de agosto 2025 y 2026",
        now=now,
        user=object(),
        session_state={
            "ultima_presentacion": {
                "__source_tool__": "analisis_economico_nominas",
                "__summary__": {"concepto_economico": "Coste empresa"},
            }
        },
    )
    assert asyncio.run(tool.handler(params, contextual)).status == "ok"
    assert calls == [(("2025-08", "2026-08"), "coste_empresa")] * 3

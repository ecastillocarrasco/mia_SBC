"""Regresiones para la exportación comparativa sin tabla histórica activa."""
import ast
import asyncio
import re
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from mia.reporting.comparisons import (
    LAST_PAYROLL_COMPARISON, explicit_month_comparison, is_export_followup, remembered_comparison,
)

ROOT = Path(__file__).resolve().parents[1] / 'src/mia'


def test_followup_does_not_need_both_tables_active():
    context = {LAST_PAYROLL_COMPARISON: {
        'periodos': ['2025-08', '2026-08'], 'campos': ['coste_empresa']}}
    assert remembered_comparison(context, 'Ahora genera el PDF de esa comparativa') == (
        ('2025-08', '2026-08'), {'coste_empresa'})
    assert remembered_comparison(context, 'Exporta agosto de 2024') is None
    assert remembered_comparison({}, 'Exporta esa comparativa') is None
    assert is_export_followup('genera el PDF del informe anterior')


def test_exporter_routes_explicit_and_followup_comparisons_without_active_results():
    tree = ast.parse((ROOT / 'modules/rrhh/informes/tools.py').read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'generar')
    calls = []

    class FakeTool:
        def __init__(self, name, description, params, handler, **kwargs):
            self.handler = handler
            self.timeout_seconds = kwargs.get('timeout_seconds', 20)

    async def mock_comparison(_deps, _ctx, periods, **kwargs):
        calls.append((periods, kwargs['concepto']))
        return SimpleNamespace(status='ok')

    def fake_plan(message, **_):
        payroll = ('nominas' in message or 'costes' in message)
        metrics = [SimpleNamespace(field=SimpleNamespace(domain='payroll', name='coste_empresa'))] if payroll else []
        return SimpleNamespace(metrics=metrics, compare=False, period=None)

    class Permissions:
        INFORMES_GENERAR = 'informes'

    ns = {
        'Tool': FakeTool,
        'InformeParams': object,
        'Permission': Permissions,
        'planner': SimpleNamespace(plan=fake_plan),
        'explicit_month_comparison': explicit_month_comparison,
        'remembered_comparison': remembered_comparison,
        'LAST_TABLE': 'ultima_presentacion',
        '_contextual_payroll_concept': lambda state: ('coste_empresa' if state.get('ultima_presentacion', {}).get('__source_tool__') == 'analisis_economico_nominas' else None),
        '_run_economic_comparison': mock_comparison,
        '_infer_concepto': lambda fields: 'coste_empresa' if 'coste_empresa' in fields else 'liquido',
        're': re,
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), node], type_ignores=[])), '<generar>', 'exec'), ns)
    tool = ns['generar'](object())
    assert tool.timeout_seconds >= 560  # dos consultas históricas independientes
    params = SimpleNamespace(formato='pdf', titulo=None, incluir_detalle=True,
                             incluir_grafico=True, incluir_narrativa=False)
    now = datetime(2026, 10, 14)
    direct = SimpleNamespace(user_message='PDF de costes de nominas agosto 2025 y 2026',
                             now=now, user=object(), session_state={})
    followup = SimpleNamespace(user_message='Ahora genera el PDF de esa comparativa',
                               now=now, user=object(), session_state={
                                   LAST_PAYROLL_COMPARISON: {'periodos': ['2025-08', '2026-08'],
                                                             'campos': ['coste_empresa']}})
    assert asyncio.run(tool.handler(params, direct)).status == 'ok'
    assert asyncio.run(tool.handler(params, followup)).status == 'ok'
    contextual = SimpleNamespace(user_message='PDF de la comparativa de agosto 2025 y 2026',
                                 now=now, user=object(), session_state={
                                     'ultima_presentacion': {'__source_tool__': 'analisis_economico_nominas',
                                                             '__summary__': {'concepto_economico': 'Coste empresa'}}})
    assert asyncio.run(tool.handler(params, contextual)).status == 'ok'
    assert calls == [(('2025-08', '2026-08'), 'coste_empresa')] * 3

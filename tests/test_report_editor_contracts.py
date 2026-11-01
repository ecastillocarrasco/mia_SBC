"""Report composition sees provenance and narrative types, never private bodies or amounts."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from mia.auth import UserContext
from mia.conversation import ToolContext, ToolRegistry
from mia.conversation.engine import _report_hint
from mia.conversation.tools import LAST_TABLE, remember_table
from mia.llm import ToolCall
from mia.llm.base import LLMCompleted, LLMRequest, Message, TextDelta
from mia.llm.fake import FakeLLMProvider, final_answer
from mia.modules.rrhh.common import Deps
from mia.modules.rrhh.informes.tools import (
    _payroll_concept_problem,
    _payroll_evolution_problem,
    generar,
    generar_ejecutivo,
)
from mia.privacy_gateway.gateway import PrivacyGateway
from mia.query.period import period_engine
from mia.reporting.content_composer import _SYSTEM, _inventory
from mia.reporting.delivery import merge_report_sources
from mia.reporting.document import Block, Document
from mia.reporting.narrative_generation import NARRATIVE_RESPONSE_SCHEMA, _parse_statements, generate_narrative_block
from mia.reporting.narrative_requirements import requested_narrative_kinds
from mia.reporting.verification import verify_artifact
from mia.settings import PrivacyGatewaySettings
from tests.dbutil import fresh_database


async def test_privacy_blocked_fact_requires_regeneration_before_satisfying_requested_facts():
    calls = []

    def script(request):
        calls.append(request)
        text = "PRIVATE_LOCATION" if len(calls) == 1 else "El total del grupo analizado es 100."
        return [
            TextDelta(json.dumps({"statements": [{"kind": "fact", "text": text, "metric": "total", "value": 100}]})),
            LLMCompleted(),
        ]

    provider = FakeLLMProvider(script)
    provider.scan_text_for_pii = lambda text: (
        [SimpleNamespace(entity_type="LOCATION", start=0, end=len(text))] if "PRIVATE_LOCATION" in text else []
    )
    block = await generate_narrative_block(
        provider, title="Prueba", backend_summary={"total": 100}, required_kinds=frozenset({"fact"})
    )
    assert block is not None and len(calls) == 2
    assert all(not s.get("evidence", {}).get("privacy_blocked") for s in block.data["statements"])


@pytest.mark.parametrize("flag", ["blocked", "period_blocked", "privacy_blocked"])
def test_editor_inventory_cannot_count_a_blocked_statement_as_available(flag):
    doc = Document(
        "Prueba",
        [
            Block(
                "narrative",
                "Análisis",
                {"statements": [{"kind": "fact", "text": "No publicable", "evidence": {flag: True}}]},
            )
        ],
    )
    assert _inventory(doc)[0]["statement_types"] == []


def test_multiformat_delivery_keeps_the_source_available_for_followup_exports():
    state = {}
    remember_table(
        state,
        {"type": "table", "columns": ["Grupo"], "rows": [["PruebasA"]]},
        5000,
        {"total": 1},
        source_tool="plantilla",
    )
    original = dict(state[LAST_TABLE])
    remember_table(
        state,
        {"type": "downloads", "items": [{"format": "pdf"}, {"format": "xlsx"}]},
        5000,
        source_tool="generar_informe",
    )
    assert state[LAST_TABLE] == original


@pytest.mark.parametrize("label", ["Líquido (neto)", "Devengado (bruto)", "", "Coste empresa"])
def test_coste_de_nominas_cannot_be_delivered_as_another_concept(label):
    ctx = SimpleNamespace(
        user_message="Analiza la evolución del coste de nóminas en T3 2026",
        user=UserContext("synthetic", "Synthetic", roles=frozenset({"mia.admin"})),
        now=datetime(2026, 10, 31, tzinfo=UTC),
    )
    source = {"__source_tool__": "analisis_economico_nominas", "__summary__": {"concepto_economico": label}}
    problem = _payroll_concept_problem(source, ctx)
    assert (problem is None) == (label == "Coste empresa")
    if problem:
        assert "concepto='coste_empresa'" in problem.summary["mensaje"]


def test_strict_narrative_schema_requires_nullable_fields_and_rejects_null_facts():

    item = NARRATIVE_RESPONSE_SCHEMA["properties"]["statements"]["items"]
    assert set(item["required"]) == set(item["properties"])
    for key in ("metric", "value", "period"):
        assert "null" in item["properties"][key]["type"]
    payload = {
        "statements": [
            {"kind": "fact", "text": "Sin respaldo", "metric": None, "value": None, "period": None},
            {"kind": "hypothesis", "text": "Posible causa", "metric": None, "value": None, "period": None},
        ]
    }
    assert [s["kind"] for s in _parse_statements(json.dumps(payload))] == ["hypothesis"]


@pytest.mark.parametrize(
    ("months", "blocked"),
    [([], True), (["2026-09"], True), (["2026-09", "2026-09"], True), (["2026-08", "2026-09"], False)],
)
def test_payroll_evolution_requires_distinct_months(months, blocked):

    ctx = SimpleNamespace(
        user_message="Analiza la evolución del coste de nóminas",
        user=UserContext("synthetic", "Synthetic", roles=frozenset({"mia.admin"})),
        now=datetime(2026, 10, 31, tzinfo=UTC),
    )
    presentation = {"__source_tool__": "analisis_economico_nominas", "__summary__": {"meses_con_datos": months}}
    assert (_payroll_evolution_problem(presentation, ctx) is not None) is blocked
    presentation["__source_tool__"] = "plantilla"
    assert _payroll_evolution_problem(presentation, ctx) is None


def test_payroll_range_hint_preserves_full_interval_before_planning():

    hint = _report_hint(
        "Analiza la evolución del coste de nóminas en 2026-07 a 2026-09",
        UserContext("synthetic", "Synthetic", roles=frozenset({"mia.admin"})),
        datetime(2026, 10, 31, tzinfo=UTC).date(),
    )
    assert "2026-07-01 a 2026-09-30" in hint


def test_single_source_recovery_preserves_full_summary_and_does_not_mutate_the_result():
    presentation = {"type": "table", "title": "Sintético", "columns": ["Grupo", "Total"], "rows": [["A", 100]]}
    summary = {"total_periodo": 100, "periodo_interpretado": "Septiembre 2026", "advertencias": ["Un solo mes"]}
    execution = SimpleNamespace(
        call=SimpleNamespace(name="analisis_economico_nominas"),
        result=SimpleNamespace(status=SimpleNamespace(value="ok"), presentation=presentation, summary=summary),
    )
    merged = merge_report_sources([execution], title="Exportación")
    assert merged["__summary__"] == summary
    assert "__summary__" not in presentation


def test_editor_inventory_exposes_scope_and_usable_narrative_kinds_without_text_or_values():
    doc = Document(
        "Sintético",
        [
            Block(
                "table",
                "Tabla",
                {
                    "columns": ["Nombre", "Total"],
                    "rows": [["PRIVATE_NAME_984", 12345]],
                    "__summary__": {
                        "nombre": "PRIVATE_NAME_984",
                        "total_periodo": 12345,
                        "estado": "activos",
                        "departamento": "PruebasA",
                    },
                },
            ),
            Block(
                "narrative",
                "Análisis",
                {
                    "statements": [
                        {"kind": "fact", "text": "PRIVATE_FACT_984", "evidence": {"value": 12345}},
                        {"kind": "hypothesis", "text": "PRIVATE_HYPOTHESIS_984"},
                        {"kind": "recommendation", "text": "PRIVATE_ACTION_984"},
                    ]
                },
            ),
        ],
    )
    inventory = _inventory(doc)
    assert inventory[0]["scope"] == {"estado": "activos", "departamento": "PruebasA"}
    assert inventory[1]["statement_types"] == ["fact", "hypothesis", "recommendation"]
    encoded = json.dumps(inventory)
    assert "PRIVATE_" not in encoded and "12345" not in encoded
    doc.blocks[1].data["statements"][0]["evidence"]["blocked"] = True
    assert "fact" not in _inventory(doc)[1]["statement_types"]


async def test_editor_instructions_do_not_create_a_fictitious_person_but_user_identifiers_remain_protected():
    provider = FakeLLMProvider(lambda request: final_answer("Listo", "Listo"))
    gateway = PrivacyGateway(
        provider,
        PrivacyGatewaySettings(enabled=True, vault_key="synthetic-test-key"),
        provider_name="test",
        model="test",
    )
    request = LLMRequest(system=_SYSTEM, messages=[Message(role="user", content='{"nombre":"PRIVATE_NAME_984"}')])
    async for _ in gateway.stream(request):
        pass
    assert "[PERSON_" not in provider.requests[0].system
    assert "PRIVATE_NAME_984" not in provider.requests[0].messages[0].content


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("PDF con hechos, hipótesis y recomendaciones separados", {"fact", "hypothesis", "recommendation"}),
        ("PDF de hechos sin hipótesis ni recomendaciones", {"fact"}),
        ("Exporta la tabla completa sin conclusiones", set()),
    ],
)
def test_requested_narrative_types_respect_explicit_exclusions(prompt, expected):
    assert requested_narrative_kinds(prompt) == expected


async def test_missing_requested_narrative_types_are_regenerated_and_still_verified():
    calls = []

    def script(request):
        calls.append(request)
        statements = [{"kind": "fact", "text": "Total 100", "metric": "total", "value": 100}]
        if len(calls) == 2:
            statements += [
                {"kind": "hypothesis", "text": "Posible causa sin confirmar"},
                {"kind": "recommendation", "text": "Contrastar otras fuentes"},
            ]
        return [TextDelta(json.dumps({"statements": statements})), LLMCompleted()]

    block = await generate_narrative_block(
        FakeLLMProvider(script),
        title="Prueba",
        backend_summary={"total": 100},
        required_kinds=frozenset({"fact", "hypothesis", "recommendation"}),
    )
    assert block is not None and len(calls) == 2
    assert {s["kind"] for s in block.data["statements"]} == {"fact", "hypothesis", "recommendation"}
    assert "NO menciones" not in calls[0].messages[0].content


async def test_a_blocked_fact_cannot_satisfy_an_explicit_requirement_for_verified_facts():
    provider = FakeLLMProvider(
        lambda request: [
            TextDelta(
                json.dumps(
                    {
                        "statements": [
                            {"kind": "fact", "text": "Total inventado 999", "metric": "total", "value": 999},
                        ]
                    }
                )
            ),
            LLMCompleted(),
        ]
    )
    assert (
        await generate_narrative_block(
            provider, title="Prueba", backend_summary={"total": 100}, required_kinds=frozenset({"fact"})
        )
        is None
    )


@pytest.mark.parametrize("expression", ["2026-07 a 2026-09", "2026-07-01 a 2026-09-30", "2026-07 – 2026-09"])
def test_numeric_range_forms_share_dates_and_label(expression):
    resolved = period_engine.resolve(expression)
    assert resolved.start.isoformat() == "2026-07-01"
    assert resolved.end.isoformat() == "2026-09-30"
    assert resolved.label == "2026-07 – 2026-09"


@pytest.mark.parametrize("expression", ["2026-09 a 2026-07", "2026-13 a 2026-14", "2026-02-30 a 2026-03-01"])
def test_invalid_numeric_ranges_do_not_produce_a_period(expression):
    assert period_engine.resolve(expression) is None


async def test_executive_selection_preserves_a_requested_full_roster_in_every_format(tmp_path):
    db = await fresh_database(tmp_path, "full-roster.db")
    directory = tmp_path / "reports"
    settings = SimpleNamespace(reports=SimpleNamespace(directory=directory, ttl_hours=24, logo_path=None))
    deps = Deps(db, settings=settings)
    registry = ToolRegistry()
    registry.register(generar(deps))
    registry.register(generar_ejecutivo(deps))
    table = {
        "type": "table",
        "title": "Plantilla",
        "columns": ["Nombre", "Departamento"],
        "rows": [[f"Persona ficticia {i}", "PruebasA"] for i in range(19)],
    }
    state = {}
    remember_table(
        state, table, 5000, {"departamento": "PruebasA", "estado": "activos", "total": 19}, source_tool="plantilla"
    )
    ctx = ToolContext(
        user=UserContext("synthetic", "Synthetic", roles=frozenset({"mia.admin"})),
        request_id=None,
        now=datetime(2026, 10, 31, tzinfo=UTC),
        session_state=state,
        user_message="Lista la plantilla activa de PruebasA y genera el mismo informe completo en PDF, Excel y Word.",
    )
    try:
        execution = await registry.execute(
            ToolCall(
                "export",
                "generar_informe_ejecutivo",
                json.dumps({"formato": ["pdf", "xlsx", "docx"], "departamento": "PruebasA"}),
            ),
            ctx,
        )
        assert execution.result.status.value == "ok"
        for item in execution.result.presentation["items"]:
            content = (directory / (item["url"].split("/")[-1] + "." + item["format"])).read_bytes()
            verify_artifact(item["format"], content, Document("Origen", [Block("table", "Plantilla", table)]))
    finally:
        await db.dispose()

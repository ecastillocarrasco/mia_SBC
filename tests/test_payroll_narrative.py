import json

import pytest

from mia.llm.base import LLMCompleted, TextDelta
from mia.llm.fake import FakeLLMProvider
from mia.reporting.narrative_generation import generate_narrative_block
from mia.reporting.payroll_narrative import payroll_context, payroll_facts, payroll_prose


async def test_single_month_explains_missing_comparisons_without_external_prose():
    def forbidden(request):
        pytest.fail("A single-month limitation requires no external generation")

    provider = FakeLLMProvider(forbidden)
    block = await generate_narrative_block(
        provider,
        title="Synthetic September",
        backend_summary={
            "concepto_economico": "Coste empresa",
            "total_periodo": 1234.56,
            "total_por_mes": {"2026-09": 1234.56},
        },
        expected_period="2026-09",
        required_kinds=frozenset({"fact", "hypothesis", "recommendation"}),
    )
    assert block is not None
    text = " ".join(statement["text"] for statement in block.data["statements"])
    assert "1.234,56 EUR" in text
    assert "no evaluar una tendencia" in text
    assert "no permiten determinar" in text
    assert "No se formula una hipótesis causal" in text
    assert "coste empresarial insuficiente" not in text
    assert not provider.requests


def test_single_month_discards_unsupported_financial_insufficiency_claim():
    prose = payroll_prose(
        [{"kind": "interpretation", "text": "El coste empresarial es insuficiente para mantener recursos."}],
        {"concepto_economico": "Coste empresa", "total_por_mes": {"2026-09": 100}},
    )
    text = " ".join(statement["text"] for statement in prose)
    assert "insuficiente para mantener" not in text
    assert "no permiten determinar" in text


@pytest.mark.parametrize(
    ("label", "term"),
    [
        ("Coste empresa", "coste empresarial"),
        ("Líquido (neto)", "líquido neto"),
        ("Devengado (bruto)", "devengado bruto"),
    ],
)
def test_payroll_facts_use_the_backend_concept_instead_of_generated_prose(label, term):
    summary = {"concepto_economico": label, "total_periodo": 1234.56, "personas_del_grupo": 19}
    facts = payroll_facts(summary, {"total_periodo": 1234.56, "personas_del_grupo": 19}, "2026-07 a 2026-09")
    assert term in facts[0]["text"] and "1.234,56 EUR" in facts[0]["text"]
    assert facts[0]["evidence"]["value"] == 1234.56
    assert facts[0]["evidence"]["origin"] == "backend"
    assert facts[0]["evidence"]["period"] == "2026-07 a 2026-09"
    assert "ingresos" not in facts[0]["text"]


def test_mixed_months_do_not_authorize_a_sustained_decline_claim():
    summary = {"concepto_economico": "Coste empresa", "total_por_mes": {"2026-07": 100, "2026-08": 200, "2026-09": 150}}
    assert payroll_context(summary)["tendencia"] == "mixta"
    result = payroll_prose(
        [
            {"kind": "fact", "text": "Ingresos inventados"},
            {"kind": "interpretation", "text": "El coste disminuye gradualmente"},
            {"kind": "recommendation", "text": "Aumentar ingresos"},
            {"kind": "hypothesis", "text": "El cambio es del 40%"},
            {
                "kind": "hypothesis",
                "text": "Las variaciones podrían deberse a cambios de plantilla; no está confirmado.",
            },
        ],
        summary,
    )
    assert [s["kind"] for s in result] == ["hypothesis"]


async def test_external_payroll_prose_receives_no_amounts_and_cannot_replace_local_facts():
    def script(request):
        return [
            TextDelta(
                json.dumps(
                    {
                        "statements": [
                            {
                                "kind": "fact",
                                "text": "El total de ingresos es 1234.56",
                                "metric": "total_periodo",
                                "value": 1234.56,
                            },
                            {
                                "kind": "hypothesis",
                                "text": "La variación podría deberse a cambios de plantilla; no está confirmado.",
                            },
                            {
                                "kind": "recommendation",
                                "text": "Contrastar los costes con la planificación de personal.",
                            },
                        ]
                    }
                )
            ),
            LLMCompleted(),
        ]

    provider = FakeLLMProvider(script)
    block = await generate_narrative_block(
        provider,
        title="PRIVATE_PAYROLL_TITLE",
        backend_summary={
            "concepto_economico": "Coste empresa",
            "total_periodo": 1234.56,
            "total_por_mes": {"2026-07": 600.0, "2026-08": 634.56},
        },
        expected_period="2026-07 a 2026-08",
        required_kinds=frozenset({"fact", "hypothesis", "recommendation"}),
    )
    assert block is not None
    facts = [s for s in block.data["statements"] if s["kind"] == "fact"]
    assert len(facts) == 1 and "coste empresarial" in facts[0]["text"]
    assert all("ingresos" not in s["text"] for s in block.data["statements"])
    prompt = provider.requests[0].messages[0].content
    assert "coste empresarial" in prompt
    assert all(value not in prompt for value in ("1234.56", "600.0", "634.56", "PRIVATE_PAYROLL_TITLE"))

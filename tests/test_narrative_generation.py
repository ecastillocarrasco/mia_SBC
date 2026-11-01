"""Fase F (integración LLM), sección 3.2: la narrativa generada por el LLM se verifica de verdad
contra el resumen real del backend antes de publicarse — ``narrative_guard`` deja de ser una librería
sin invocar (ver ``mia.reporting.narrative_generation``). Usa ``FakeLLMProvider`` (determinista, sin
red real) para poder comprobar comportamientos concretos: respuesta correcta, discrepancia bloqueada,
JSON malformado, reintento, y ausencia de proveedor."""

from __future__ import annotations

import json

from mia.llm.base import LLMCompleted, LLMRequest, TextDelta
from mia.llm.fake import FakeLLMProvider
from mia.reporting.narrative_generation import _flatten_numeric, generate_narrative_block

BACKEND_SUMMARY = {
    "total_staff": 120.0,
    "absence_rate": 4.2,
    "por_departamento": {"Cocina": {"total": 60000.0}, "Recepción": {"total": 60000.0}},
}


def _script_returning(payload: dict) -> object:
    def script(request: LLMRequest) -> list[object]:
        return [TextDelta(json.dumps(payload)), LLMCompleted()]

    return script


async def test_generates_a_verified_block_when_the_llm_cites_real_figures() -> None:
    fake = FakeLLMProvider(
        script=_script_returning(
            {
                "statements": [
                    {
                        "kind": "fact",
                        "text": "La plantilla es de 120 personas.",
                        "metric": "total_staff",
                        "value": 120.0,
                    },
                    {"kind": "recommendation", "text": "Revisar la cobertura de Cocina en temporada alta."},
                ]
            }
        )
    )
    block = await generate_narrative_block(fake, title="Informe Q3", backend_summary=BACKEND_SUMMARY)
    assert block is not None
    assert block.kind == "narrative"
    texts = [s["text"] for s in block.data["statements"]]
    assert any("120 personas" in t for t in texts)
    assert not any("BLOQUEADA" in t for t in texts)


async def test_blocks_a_fact_that_contradicts_the_backend() -> None:
    fake = FakeLLMProvider(
        script=_script_returning(
            {
                "statements": [
                    {
                        "kind": "fact",
                        "text": "La plantilla es de 300 personas.",
                        "metric": "total_staff",
                        "value": 300.0,
                    }
                ]
            }
        )
    )
    block = await generate_narrative_block(fake, title="Informe Q3", backend_summary=BACKEND_SUMMARY)
    assert block is not None
    text = block.data["statements"][0]["text"]
    assert "BLOQUEADA" in text
    assert "120.0" in text  # la cifra real queda visible


async def test_fact_citing_a_nested_metric_is_verified_against_the_flattened_value() -> None:
    fake = FakeLLMProvider(
        script=_script_returning(
            {
                "statements": [
                    {
                        "kind": "fact",
                        "text": "Cocina gastó 60.000 €.",
                        "metric": "por_departamento.Cocina.total",
                        "value": 60000.0,
                    }
                ]
            }
        )
    )
    block = await generate_narrative_block(fake, title="Informe Q3", backend_summary=BACKEND_SUMMARY)
    assert block is not None
    assert "BLOQUEADA" not in block.data["statements"][0]["text"]


async def test_malformed_json_response_returns_none_without_raising() -> None:
    fake = FakeLLMProvider(script=lambda req: [TextDelta("esto no es json en absoluto"), LLMCompleted()])
    block = await generate_narrative_block(fake, title="Informe Q3", backend_summary=BACKEND_SUMMARY)
    assert block is None


async def test_no_llm_provider_returns_none_immediately() -> None:
    block = await generate_narrative_block(None, title="Informe Q3", backend_summary=BACKEND_SUMMARY)
    assert block is None


async def test_individual_report_does_not_send_sensitive_figures_for_external_narration() -> None:
    """``authorized_subjects`` autoriza CITAR un nombre en la narrativa publicada (ver
    ``test_fase_f_integration.py::test_generate_narrative_block_does_not_block_the_subject_of_an_individual_report``),
    nunca exime el resumen de la minimización incondicional que ya aplica
    ``redact_individual_amounts`` al inicio de ``generate_narrative_block`` — la propiedad real de esta
    prueba es que ninguna cifra individual (aquí, "salario") llega al proveedor externo, sea cual sea el
    número de peticiones que se hagan."""
    fake = FakeLLMProvider()
    block = await generate_narrative_block(
        fake,
        title="Informe individual",
        backend_summary={"nombre": "Persona sintética", "salario": 1234},
        authorized_subjects=frozenset({"Persona sintética"}),
    )
    assert block is None
    sent_text = " ".join(req.system + " ".join(m.content for m in req.messages) for req in fake.requests)
    assert "1234" not in sent_text


async def test_aggregate_narration_omits_nested_individual_values_before_flattening() -> None:
    fake = FakeLLMProvider(script=_script_returning({"statements": []}))
    await generate_narrative_block(
        fake,
        title="Informe agregado",
        backend_summary={
            "total_staff": 30,
            "ranking": [
                {"persona": "Persona sintética", "importe": 9876},
            ],
        },
    )
    outgoing = " ".join(message.content for request in fake.requests for message in request.messages)
    assert "9876" not in outgoing and "Persona sintética" not in outgoing
    assert '"total_staff": 30.0' in outgoing


async def test_fact_without_metric_is_dropped_but_other_statements_survive() -> None:
    fake = FakeLLMProvider(
        script=_script_returning(
            {
                "statements": [
                    {"kind": "fact", "text": "Algo sin respaldo.", "metric": None, "value": None},
                    {"kind": "hypothesis", "text": "Quizá suba el año que viene."},
                ]
            }
        )
    )
    block = await generate_narrative_block(fake, title="Informe Q3", backend_summary=BACKEND_SUMMARY)
    assert block is not None
    texts = [s["text"] for s in block.data["statements"]]
    assert "Algo sin respaldo." not in texts
    assert "Quizá suba el año que viene." in texts


async def test_retries_once_when_the_first_response_is_unparseable() -> None:
    calls = {"n": 0}

    def script(request: LLMRequest) -> list[object]:
        calls["n"] += 1
        if calls["n"] == 1:
            return [TextDelta("respuesta rota"), LLMCompleted()]
        return [
            TextDelta(json.dumps({"statements": [{"kind": "interpretation", "text": "Segundo intento correcto."}]})),
            LLMCompleted(),
        ]

    fake = FakeLLMProvider(script=script)
    block = await generate_narrative_block(fake, title="Informe Q3", backend_summary=BACKEND_SUMMARY)
    assert calls["n"] == 2
    assert block is not None
    assert block.data["statements"][0]["text"] == "Segundo intento correcto."


def test_flatten_numeric_covers_nested_dicts_up_to_max_depth() -> None:
    flat = _flatten_numeric(BACKEND_SUMMARY)
    assert flat["total_staff"] == 120.0
    assert flat["por_departamento.Cocina.total"] == 60000.0
    assert "por_departamento" not in flat  # el propio dict no es numérico, no se incluye


async def test_unknown_metric_is_not_published_as_a_verified_fact():
    fake = FakeLLMProvider(
        script=_script_returning(
            {
                "statements": [
                    {
                        "kind": "fact",
                        "text": "El supuesto beneficio es 9000.",
                        "metric": "beneficio_inventado",
                        "value": 9000,
                    }
                ]
            }
        )
    )
    assert await generate_narrative_block(fake, title="Informe", backend_summary=BACKEND_SUMMARY) is None

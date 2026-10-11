"""Nuevos tipos de bloque del motor documental universal (Bloque II, Fase D, sección 9):
``warnings``, ``narrative``, ``methodology``, ``annex`` — construidos con sus propios validadores en
``mia.modules.rrhh.informes.document``, retrocompatibles con el esquema existente (``kpis``/
``section``/``table``/``chart``, sin tocar)."""

from __future__ import annotations

import pytest

from mia.analytics.homogeneity import check_populations
from mia.modules.rrhh.informes.document import (
    annex_block,
    methodology_block,
    narrative_block,
    narrative_statement,
    warnings_block,
)


def test_warnings_block_accepts_real_homogeneity_issues_via_to_dict() -> None:
    issues = [i.to_dict() for i in check_populations(0, 5, label_a="Cocina", label_b="Pisos")]
    block = warnings_block("Advertencias", issues)
    assert block.kind == "warnings"
    assert block.data["items"][0]["code"] == "POPULATION_EMPTY"
    assert block.data["items"][0]["severity"] == "blocker"


def test_warnings_block_rejects_unknown_severity() -> None:
    with pytest.raises(ValueError, match="Severidad"):
        warnings_block("Advertencias", [{"severity": "catastrofico", "code": "X", "message": "m"}])


def test_warnings_block_rejects_a_mute_warning() -> None:
    with pytest.raises(ValueError, match="código y mensaje"):
        warnings_block("Advertencias", [{"severity": "info", "code": "", "message": ""}])


def test_narrative_fact_requires_evidence() -> None:
    with pytest.raises(ValueError, match="evidencia verificable"):
        narrative_statement("fact", "La plantilla creció un 12%")


def test_narrative_fact_with_evidence_is_accepted() -> None:
    stmt = narrative_statement(
        "fact", "La plantilla creció un 12%",
        evidence={"source": "mia.analytics.stats", "metric": "total_staff", "period": "2026", "value": 12.0},
    )
    assert stmt["kind"] == "fact"
    assert stmt["evidence"]["value"] == 12.0


def test_narrative_interpretation_hypothesis_and_recommendation_do_not_require_evidence() -> None:
    for kind in ("interpretation", "hypothesis", "recommendation"):
        stmt = narrative_statement(kind, "texto libre")
        assert stmt["kind"] == kind
        assert stmt["evidence"] == {}


def test_narrative_block_keeps_statements_in_order() -> None:
    statements = [
        narrative_statement("fact", "hecho", evidence={"source": "x", "value": 1}),
        narrative_statement("hypothesis", "quizá"),
    ]
    block = narrative_block("Hallazgos", statements)
    assert block.kind == "narrative"
    assert [s["kind"] for s in block.data["statements"]] == ["fact", "hypothesis"]


def test_methodology_block_keeps_notes_as_a_list() -> None:
    block = methodology_block("Metodología", ["Nota 1", "Nota 2"])
    assert block.kind == "methodology"
    assert block.data["notes"] == ["Nota 1", "Nota 2"]


def test_annex_block_never_truncates_silently() -> None:
    rows = [[i, f"Persona {i}"] for i in range(10)]
    block = annex_block("Detalle", ["ID", "Nombre"], rows, max_rows=4)
    assert block.kind == "annex"
    assert block.data["total_rows"] == 10
    assert block.data["truncated"] is True
    assert len(block.data["rows"]) == 4


def test_annex_block_below_the_limit_is_not_marked_truncated() -> None:
    rows = [[i] for i in range(3)]
    block = annex_block("Detalle", ["ID"], rows, max_rows=4)
    assert block.data["truncated"] is False
    assert block.data["total_rows"] == 3
    assert len(block.data["rows"]) == 3

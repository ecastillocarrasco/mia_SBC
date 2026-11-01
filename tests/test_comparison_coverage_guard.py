from types import SimpleNamespace

import pytest

from mia.conversation import ConversationEngine, ToolRegistry
from mia.conversation.engine import FinalAnswer
from mia.conversation.planning import TaskPlan
from mia.conversation.tools import ToolExecution, ToolResult, ToolStatus
from mia.data import Database
from mia.llm import ToolCall
from mia.llm.fake import FakeLLMProvider, final_answer
from mia.reporting.comparison_guard import incomplete_payroll_comparison


def source(year, *, missing=False, status=ToolStatus.OK, tool="analisis_economico_nominas"):
    return ToolExecution(
        ToolCall(str(year), tool, "{}"),
        ToolResult(
            status,
            {
                "periodo_interpretado": str(year),
                "meses_con_datos": [f"{year}-09"] if missing else [f"{year}-09", f"{year}-10"],
                "meses_sin_datos": [f"{year}-10"] if missing else None,
                "total_periodo": 123456.78,
            },
        ),
        0,
        None,
    )


@pytest.mark.parametrize("partial_first", [False, True])
async def test_incomplete_periods_override_an_unsupported_model_trend(partial_first):
    db = Database("sqlite+aiosqlite:///:memory:")
    try:
        engine = ConversationEngine(
            llm=FakeLLMProvider(lambda req: final_answer("Listo", "Listo")), tools=ToolRegistry(), db=db
        )
        turn = SimpleNamespace(
            executions=[source(2025, missing=partial_first), source(2026, missing=not partial_first)], state={}
        )
        result = engine._verify_candidate(
            FinalAnswer("El coste baja", "neutra", "El gasto presenta una tendencia a la baja."),
            TaskPlan("Compara costes anuales", frozenset()),
            turn,
            planned=False,
            missing=[],
            pending_steps=[],
        )
        assert "tendencia a la baja" not in result.text
        assert "comparación es parcial" in result.text
        assert f"{2025 if partial_first else 2026}-10" in result.text
        assert "123456" not in result.text
        assert "baja" not in result.speech
    finally:
        await db.dispose()


def test_complete_periods_keep_normal_comparison():
    assert incomplete_payroll_comparison([source(2025), source(2026)]) is None


def test_single_period_is_not_treated_as_a_comparison():
    assert incomplete_payroll_comparison([source(2026, missing=True)]) is None


def test_failed_or_unrelated_tools_are_not_comparison_evidence():
    assert incomplete_payroll_comparison([source(2025), source(2026, missing=True, status=ToolStatus.ERROR)]) is None
    assert incomplete_payroll_comparison([source(2025), source(2026, missing=True, tool="plantilla")]) is None

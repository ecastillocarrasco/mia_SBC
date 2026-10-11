"""Fase F, sección 3.2: ``narrative_guard``/``narrative_generation`` conectados de verdad a
``generar_informe`` (``incluir_narrativa=True``), no una librería aislada sin invocación. Prueba de
extremo a extremo: el tool real genera un PDF con una sección de hallazgos redactada por un
``FakeLLMProvider`` (determinista) y verificada contra el resumen real antes de publicarse."""

from __future__ import annotations

import datetime
import io
import json
from pathlib import Path
from types import SimpleNamespace

from pypdf import PdfReader

from mia.auth import UserContext
from mia.conversation import ToolContext
from mia.conversation.tools import LAST_TABLE
from mia.llm import ToolCall
from mia.llm.base import LLMCompleted, LLMRequest, TextDelta
from mia.llm.fake import FakeLLMProvider
from mia.modules.rrhh import build_registry
from tests.dbutil import fresh_database

ADMIN = UserContext("u", "Enrique", roles=frozenset({"mia.admin"}))

_PRESENTATION = {
    "type": "table",
    "title": "Plantilla por departamento",
    "columns": ["Departamento", "Personas"],
    "rows": [["Cocina", 4], ["Recepción", 4]],
    "__summary__": {"total_staff": 8.0, "departamentos": 2.0},
}


def _stub_settings(reports_dir: Path) -> SimpleNamespace:
    return SimpleNamespace(reports=SimpleNamespace(directory=str(reports_dir), ttl_hours=24, logo_path=None))


def _script_returning(payload: dict) -> object:
    def script(request: LLMRequest) -> list[object]:
        return [TextDelta(json.dumps(payload)), LLMCompleted()]
    return script


async def _generate_pdf_text(tmp_path: Path, db_name: str, fake: FakeLLMProvider) -> str:
    db = await fresh_database(tmp_path, db_name)
    reports_dir = tmp_path / db_name.replace(".db", "")
    registry = build_registry(db, settings=_stub_settings(reports_dir), llm=fake)
    ctx = ToolContext(
        user=ADMIN, request_id=None, now=datetime.date(2026, 10, 11), session_state={LAST_TABLE: _PRESENTATION}
    )
    execution = await registry.execute(
        ToolCall("c", "generar_informe", json.dumps({"formato": "pdf", "incluir_narrativa": True})), ctx
    )
    assert execution.result.status.value == "ok"
    report_id = execution.result.presentation["url"].rsplit("/", 1)[-1]
    content = (reports_dir / f"{report_id}.pdf").read_bytes()
    return "".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages)


async def test_generar_informe_with_narrativa_attaches_a_verified_block(tmp_path: Path) -> None:
    fake = FakeLLMProvider(
        script=_script_returning(
            {"statements": [{"kind": "fact", "text": "La plantilla es de 8 personas.", "metric": "total_staff", "value": 8.0}]}
        )
    )
    text = await _generate_pdf_text(tmp_path, "reports_narrativa.db", fake)
    assert "La plantilla es de 8 personas" in text
    assert "BLOQUEADA" not in text


async def test_generar_informe_narrativa_blocks_a_wrong_llm_figure(tmp_path: Path) -> None:
    fake = FakeLLMProvider(
        script=_script_returning(
            {"statements": [{"kind": "fact", "text": "La plantilla es de 500 personas.", "metric": "total_staff", "value": 500.0}]}
        )
    )
    text = await _generate_pdf_text(tmp_path, "reports_narrativa_wrong.db", fake)
    assert "BLOQUEADA" in text
    assert "8.0" in text  # la cifra real (total_staff del resumen) queda visible


async def test_generar_informe_without_narrativa_flag_never_calls_the_llm(tmp_path: Path) -> None:
    """Control: por defecto (incluir_narrativa=False) no se gasta ninguna llamada al LLM — la
    narrativa es opt-in, no un coste oculto en cada exportación de tabla."""
    fake = FakeLLMProvider(script=_script_returning({"statements": []}))
    db = await fresh_database(tmp_path, "reports_sin_narrativa.db")
    registry = build_registry(db, settings=_stub_settings(tmp_path / "informes_sin"), llm=fake)
    ctx = ToolContext(
        user=ADMIN, request_id=None, now=datetime.date(2026, 10, 11), session_state={LAST_TABLE: _PRESENTATION}
    )
    execution = await registry.execute(ToolCall("c", "generar_informe", json.dumps({"formato": "pdf"})), ctx)
    assert execution.result.status.value == "ok"
    assert fake.requests == []

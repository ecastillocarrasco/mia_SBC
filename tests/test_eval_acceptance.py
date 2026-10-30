import io
import json

import httpx
import pytest
from openpyxl import Workbook
from tools.eval_acceptance import (
    SUITE,
    check_downloads,
    check_result,
    downloads,
    missing_bindings,
    question_list,
    run_case,
    stream_turn,
)


def test_suite_has_unique_cases_and_every_case_has_acceptance_criteria():
    cases = json.loads(SUITE.read_text(encoding="utf-8"))["cases"]
    assert len(cases) >= 30
    assert len({case["id"] for case in cases}) == len(cases)
    assert all(case["acceptance"] and case["turns"] for case in cases)
    assert "E36" in question_list(cases)


def test_http_success_alone_does_not_satisfy_tools_plan_or_references():
    result = {"status": "ok", "tools": [], "summaries": [], "speech": "Listo"}
    spec = {
        "tools_all": ["plantilla"],
        "require_plan": True,
        "summary_references": [{"tool": "plantilla", "key": "total", "reference": "total_activos"}],
    }
    assert set(check_result(result, set(), spec, {"total_activos": 3})) == {
        "herramientas_requeridas",
        "sin_plan_explicito",
        "dato_no_coincide_con_referencia",
    }


def test_authorization_failure_is_not_counted_as_a_successful_tool():
    result = {"status": "ok", "tools": [{"name": "nominas", "status": "permission_denied"}]}
    assert check_result(result, set(), {"forbidden_tools": ["nominas"]}, {}) == []
    result["tools"][0]["status"] = "ok"
    assert "herramienta_no_autorizada" in check_result(result, set(), {"forbidden_tools": ["nominas"]}, {})


def test_downloads_cannot_redirect_to_another_host_or_arbitrary_endpoint():
    result = {
        "presentations": [
            {"type": "download", "format": "pdf", "url": "https://example.test/report.pdf"},
            {"type": "download", "format": "xlsx", "url": "/api/admin"},
            {"type": "table", "format": "docx", "url": "/api/reports/" + "a" * 32},
        ]
    }
    assert downloads(result) == {}


def test_references_and_prompt_variables_are_both_required():
    case = {"turns": [{"prompt": "Cuenta $departamento", "summary_references": [{"reference": "total"}]}]}
    assert missing_bindings(case, {"departamento": "Cocina"}) == {"total"}


async def test_missing_identity_is_pending_and_never_reported_as_passed(monkeypatch):
    monkeypatch.delenv("MIA_EVAL_TOKEN_GLOBAL", raising=False)
    case = {"id": "x", "turns": [{"prompt": "Hola"}]}
    assert (await run_case(case, "http://127.0.0.1:5001", {}))["status"] == "pending"


async def test_stream_requires_the_actual_final_result():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text='event: speech\ndata: {"type":"speech","text":"Listo"}\n\n')
    )
    async with httpx.AsyncClient(base_url="http://dev.test", transport=transport) as client:
        with pytest.raises(ValueError, match="stream_sin_resultado_final"):
            await stream_turn(client, "Hola", None)


async def test_corrupt_zip_is_not_a_valid_excel_download():
    result = {"presentations": [{"type": "download", "format": "xlsx", "url": "/api/reports/" + "a" * 32}]}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"PK archivo corrupto"))
    async with httpx.AsyncClient(base_url="http://dev.test", transport=transport) as client:
        assert await check_downloads(client, result, ["xlsx"]) == ["archivo_xlsx_ilegible"]


async def test_readable_export_with_swapped_people_and_values_is_rejected():
    book = Workbook()
    sheet = book.active
    sheet.append(["Persona", "Horas"])
    sheet.append(["Persona A", 20])
    sheet.append(["Persona B", 10])
    content = io.BytesIO()
    book.save(content)
    book.close()
    result = {"presentations": [{"type": "download", "format": "xlsx", "url": "/api/reports/" + "a" * 32}]}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=content.getvalue()))
    original = {"columns": ["Persona", "Horas"], "rows": [["Persona A", 10], ["Persona B", 20]]}
    async with httpx.AsyncClient(base_url="http://dev.test", transport=transport) as client:
        assert await check_downloads(client, result, ["xlsx"], original) == ["archivo_xlsx_no_coincide_con_origen"]


async def test_structural_success_does_not_replace_business_review(monkeypatch):
    monkeypatch.setenv("MIA_EVAL_TOKEN_GLOBAL", "token-sintetico-de-prueba")

    async def successful_stream(client, prompt, session):
        return {"status": "ok", "session_id": "sesion-sintetica", "speech": "Listo"}, set()

    monkeypatch.setattr("tools.eval_acceptance.stream_turn", successful_stream)
    case = {"id": "x", "review_required": True, "turns": [{"prompt": "Analiza"}]}
    result = await run_case(case, "http://127.0.0.1:5001", {})
    assert result["status"] == "review"
    assert "token-sintetico-de-prueba" not in json.dumps(result)

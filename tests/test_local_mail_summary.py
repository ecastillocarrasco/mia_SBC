from dataclasses import replace

import httpx
import pytest

from mia.auth import UserContext
from mia.conversation import ConversationEngine
from mia.conversation.tools import ToolRegistry, ToolStatus
from mia.llm.fake import FakeLLMProvider
from mia.modules.correo.summary import direct_summary_arguments
from mia.modules.correo.tools import register as register_mail
from tests.dbutil import fresh_database
from tests.test_correo_tools import ADMIN, _ctx, _deps, _graph, _message


@pytest.mark.parametrize("message", ["Resume mis últimos cinco correos recibidos.", "¿Puedes resumirme los 5 correos?"])
def test_standalone_summary_is_resolved_locally(message):
    assert direct_summary_arguments(replace(_ctx(), user_message=message)) == {"limite": 5}


@pytest.mark.parametrize(
    "message",
    [
        "Resume mis últimos cinco correos y envía una respuesta.",
        "Resume mis últimos once correos.",
        "Resume mis últimos 50 correos.",
        "Resume mis últimos cinco correos de ayer.",
        "Borra los cinco correos.",
    ],
)
def test_compound_or_filtered_requests_remain_with_the_planner(message):
    assert direct_summary_arguments(replace(_ctx(), user_message=message)) is None


async def test_each_authorized_body_has_a_local_extract_without_model_exposure(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        messages = []
        for index in range(5):
            message = _message(f"m{index}", read=True)
            message["subject"] = f"SYNTHETIC_SUBJECT_{index}"
            message["body"] = {"contentType": "text", "content": f"PRIVATE_BODY_{index}. Second sentence."}
            messages.append(message)
        return httpx.Response(200, json={"value": messages})

    graph = _graph(handler)
    registry = ToolRegistry()
    register_mail(registry, _deps(graph))
    provider = FakeLLMProvider(lambda request: pytest.fail("Mail bodies must remain local"))
    db = await fresh_database(tmp_path)
    prompt = "Resume mis últimos cinco correos recibidos."
    try:
        engine = ConversationEngine(llm=provider, tools=registry, db=db)
        result = await engine.complete(message=prompt, user=ADMIN, session_id=None)
        assert result.status == "ok"
        assert len(requests) == 1
        assert requests[0].method == "GET"
        assert requests[0].url.params["$top"] == "5"
        assert "body" in requests[0].url.params["$select"].split(",")
        assert not provider.requests
        # Inspect actual native tool output independently from the engine result.
        ctx = replace(_ctx(), user_message=prompt)
        execution = (await registry.execute_all(registry.direct_read_calls(ctx), ctx))[0]
        answer = execution.result.verified_answer
        assert answer is not None
        for index in range(5):
            assert f"PRIVATE_BODY_{index}" in answer
            assert f"SYNTHETIC_SUBJECT_{index}" in answer
        assert answer.count("Extracto:") == 5
        assert "PRIVATE_BODY" not in execution.as_llm_output()
        assert "SYNTHETIC_SUBJECT" not in execution.as_llm_output()
        assert execution.result.status is ToolStatus.OK
        assert not registry.direct_read_calls(replace(ctx, user=UserContext("no-role", "Synthetic")))
    finally:
        await db.dispose()
        await graph.aclose()


async def test_source_failure_does_not_fabricate_summary_or_retry_through_model(tmp_path):
    graph = _graph(lambda request: httpx.Response(403, json={"error": {"code": "AccessDenied"}}))
    registry = ToolRegistry()
    register_mail(registry, _deps(graph))
    provider = FakeLLMProvider(lambda request: pytest.fail("No model fallback on a denied source"))
    db = await fresh_database(tmp_path)
    try:
        result = await ConversationEngine(llm=provider, tools=registry, db=db).complete(
            message="Resume mis últimos cinco correos recibidos.", user=ADMIN, session_id=None
        )
        assert result.status == "error"
        assert not provider.requests
    finally:
        await db.dispose()
        await graph.aclose()

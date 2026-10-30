"""Explicit plans for acceptance scripts that predate the planning protocol.

The real engine validates and executes the plan. Only the legacy script's view
omits planning messages, preserving its original business-call assertions.
"""

from collections.abc import Callable
from dataclasses import replace

from mia.conversation.planning import PLAN_TOOL
from mia.llm.base import LLMEvent, LLMRequest
from mia.llm.fake import tool_call


def planned_script(
    script: Callable[[LLMRequest], list[LLMEvent]],
    steps: tuple[str, ...] | Callable[[LLMRequest], tuple[str, ...]],
) -> Callable[[LLMRequest], list[LLMEvent]]:
    def respond(request: LLMRequest) -> list[LLMEvent]:
        if "selected_indices" in (request.response_schema or {}).get("properties", {}):
            return script(request)
        plan_ids = {
            call.call_id
            for message in request.messages
            for call in (message.tool_calls or ())
            if call.name == PLAN_TOOL
        }
        if not plan_ids and any(schema.name == PLAN_TOOL for schema in request.tools):
            names = steps(request) if callable(steps) else steps
            return tool_call(
                PLAN_TOOL,
                {
                    "pasos": [
                        {
                            "objetivo": f"Ejecutar {name}",
                            "herramientas": [name],
                            "depende_de": [index - 1] if index else [],
                        }
                        for index, name in enumerate(names)
                    ]
                },
                call_id="acceptance_plan",
            )
        messages = [
            message
            for message in request.messages
            if message.tool_call_id not in plan_ids
            and not any(call.call_id in plan_ids for call in (message.tool_calls or ()))
        ]
        return script(replace(request, messages=messages))

    return respond

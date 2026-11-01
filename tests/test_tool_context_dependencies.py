import asyncio
from datetime import UTC, datetime

import pytest
from pydantic import BaseModel

from mia.auth import UserContext
from mia.conversation import Tool, ToolContext, ToolRegistry, ToolResult, ToolStatus
from mia.llm import ToolCall


class Params(BaseModel):
    pass


@pytest.mark.parametrize("consumer_first", [False, True])
async def test_context_consumers_wait_for_source_in_the_same_batch(consumer_first):
    registry = ToolRegistry()
    order = []

    async def listing(params, ctx):
        await asyncio.sleep(0)
        ctx.session_state["refs"] = {"c1": "synthetic-message"}
        order.append("listing")
        return ToolResult.ok({"listed": 1})

    async def opening(params, ctx):
        assert ctx.session_state["refs"]["c1"] == "synthetic-message"
        order.append("opening")
        return ToolResult.ok({"opened": 1})

    registry.register(Tool("list", "List", Params, listing, produces_context=frozenset({"refs"})))
    registry.register(Tool("open", "Open", Params, opening, requires_context=frozenset({"refs"})))
    names = ["open", "list"] if consumer_first else ["list", "open"]
    result = await registry.execute_all(
        [ToolCall(name, name, "{}") for name in names],
        ToolContext(UserContext("synthetic", "Synthetic"), None, datetime.now(UTC)),
    )
    assert order == ["listing", "opening"]
    assert [e.call.name for e in result] == names
    assert all(e.result.status is ToolStatus.OK for e in result)

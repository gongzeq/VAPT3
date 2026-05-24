from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from secbot.agent.runner import AgentRunner, AgentRunSpec
from secbot.agent.tools.base import Tool
from secbot.agent.tools.registry import ToolRegistry
from secbot.config.schema import AgentDefaults
from secbot.policy import PolicyContext
from secbot.providers.base import LLMResponse, ToolCallRequest

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars


class _SimpleTool(Tool):
    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._name

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "additionalProperties": True}

    async def execute(self, **kwargs: Any) -> str:
        return f"executed:{self._name}"


@pytest.mark.asyncio
async def test_runner_uses_policy_aware_execute_prepared_path() -> None:
    provider = MagicMock()
    call_count = {"n": 0}
    captured_second_call: list[dict[str, Any]] = []

    async def chat_with_retry(*, messages: list[dict[str, Any]], **kwargs: Any) -> LLMResponse:
        del kwargs
        call_count["n"] += 1
        if call_count["n"] == 1:
            return LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="call_1",
                        name="blackboard_write",
                        arguments={
                            "kind": "finding",
                            "payload": {"title": "worker finding"},
                        },
                    )
                ],
            )
        captured_second_call[:] = messages
        return LLMResponse(content="done", tool_calls=[])

    provider.chat_with_retry = chat_with_retry
    tools = ToolRegistry(
        policy_context=PolicyContext(caller_kind="worker", worker_id="worker-1")
    )
    tools.register(_SimpleTool("blackboard_write"))

    result = await AgentRunner(provider).run(
        AgentRunSpec(
            initial_messages=[],
            tools=tools,
            model="test-model",
            max_iterations=3,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        )
    )

    assert result.final_content == "done"
    assert result.tool_events[0]["status"] == "error"
    assert result.tool_events[0]["detail"].startswith("policy_denied")
    assert any(
        msg.get("role") == "tool" and "policy_denied" in str(msg.get("content"))
        for msg in captured_second_call
    )

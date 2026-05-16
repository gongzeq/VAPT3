"""Regression tests for one-shot subagent isolation."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from secbot.agent.loop import AgentLoop
from secbot.agent.subagent import SubagentManager
from secbot.bus.queue import MessageBus
from secbot.config.schema import AgentDefaults

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars


@pytest.mark.asyncio
async def test_subagent_announces_only_summary_not_child_history(tmp_path):
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    )

    child_messages = [
        {"role": "system", "content": "child system"},
        {"role": "user", "content": "scan target"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call_1", "function": {"name": "read_file"}}],
        },
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "name": "read_file",
            "content": "CHILD_INTERMEDIATE_SECRET",
        },
        {"role": "assistant", "content": "concise child summary"},
    ]

    async def fake_run(spec):
        assert spec.initial_messages[0]["role"] == "system"
        assert spec.initial_messages[1] == {"role": "user", "content": "scan target"}
        return SimpleNamespace(
            stop_reason="completed",
            final_content="concise child summary",
            error=None,
            tool_events=[{"name": "read_file", "status": "ok", "detail": "read"}],
            messages=child_messages,
            tools_used=["read_file"],
            usage={},
            had_injections=False,
        )

    mgr.runner.run = AsyncMock(side_effect=fake_run)

    await mgr.spawn(
        task="scan target",
        label="scanner",
        origin_channel="cli",
        origin_chat_id="direct",
        session_key="cli:direct",
    )
    await _gather_running(mgr)

    injected = await bus.consume_inbound()
    assert injected.metadata["injected_event"] == "subagent_result"
    assert "concise child summary" in injected.content
    assert "CHILD_INTERMEDIATE_SECRET" not in injected.content
    assert "tool_call_id" not in injected.content


@pytest.mark.asyncio
async def test_delegate_task_parent_history_gets_only_child_summary(tmp_path):
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]

    child_messages = [
        {"role": "system", "content": "child system"},
        {"role": "user", "content": "investigate target"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call_1", "function": {"name": "read_file"}}],
        },
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "name": "read_file",
            "content": "CHILD_INTERMEDIATE_SECRET",
        },
        {"role": "assistant", "content": "final child summary"},
    ]

    async def fake_child_run(_spec):
        return SimpleNamespace(
            stop_reason="completed",
            final_content="final child summary",
            error=None,
            tool_events=[{"name": "read_file", "status": "ok", "detail": "read"}],
            messages=child_messages,
            tools_used=["read_file"],
            usage={},
            had_injections=False,
        )

    async def fake_parent_run(initial_messages, **_kwargs):
        rendered = str(initial_messages)
        assert "final child summary" in rendered
        assert "CHILD_INTERMEDIATE_SECRET" not in rendered
        assert "tool_call_id" not in rendered
        return (
            "parent acknowledged",
            [],
            [*initial_messages, {"role": "assistant", "content": "parent acknowledged"}],
            "completed",
            False,
        )

    loop.subagents.runner.run = AsyncMock(side_effect=fake_child_run)
    loop._run_agent_loop = fake_parent_run  # type: ignore[method-assign]

    await loop.subagents.spawn(
        task="investigate target",
        label="scanner",
        origin_channel="cli",
        origin_chat_id="parent",
        session_key="cli:parent",
    )
    await _gather_running(loop.subagents)

    injected = await asyncio.wait_for(bus.consume_inbound(), timeout=1)
    await loop._process_message(injected)

    session = loop.sessions.get_or_create("cli:parent")
    persisted = "\n".join(str(message) for message in session.messages)
    assert "final child summary" in persisted
    assert "parent acknowledged" in persisted
    assert "CHILD_INTERMEDIATE_SECRET" not in persisted
    assert "tool_call_id" not in persisted


async def _gather_running(mgr: SubagentManager) -> None:
    tasks = list(mgr._running_tasks.values())
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

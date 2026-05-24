from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from secbot.agent.loop import AgentLoop
from secbot.bus.queue import MessageBus
from secbot.config.schema import BudgetConfig


@pytest.mark.asyncio
async def test_run_loop_injects_budget_exceeded_and_broadcasts_checkpoint(
    monkeypatch,
    tmp_path,
) -> None:
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        budget_config=BudgetConfig(enabled=True, tool_calls_max=0),
    )

    events: list[tuple[str, str, dict]] = []

    class _FakeWebSocket:
        async def broadcast_agent_event(self, chat_id: str, type: str, payload: dict) -> None:
            events.append((chat_id, type, payload))

    monkeypatch.setattr(
        "secbot.channels.websocket.WebSocketChannel.get_active_instance",
        staticmethod(lambda: _FakeWebSocket()),
    )

    captured = {}

    async def fake_run(spec):
        captured["messages"] = spec.initial_messages
        return SimpleNamespace(
            final_content="done",
            tools_used=[],
            messages=spec.initial_messages,
            stop_reason="done",
            had_injections=False,
            usage={},
        )

    loop.runner.run = AsyncMock(side_effect=fake_run)

    await loop._run_agent_loop(
        [
            {"role": "system", "content": "old system"},
            {"role": "user", "content": "go"},
        ],
        channel="websocket",
        chat_id="chat-1",
    )

    assert any("[BUDGET_EXCEEDED]" in msg.get("content", "") for msg in captured["messages"])
    assert events[0][0] == "chat-1"
    assert events[0][1] == "checkpoint_required"
    assert events[0][2]["reason"] == "budget_exhausted"
    assert events[0][2]["budget"]["status"] == "EXCEEDED"

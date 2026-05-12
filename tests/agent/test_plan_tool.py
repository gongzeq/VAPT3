from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from secbot.agent.tools.plan import WritePlanTool


@pytest.mark.asyncio
async def test_write_plan_tool_records_plan_without_websocket():
    tool = WritePlanTool()

    result = await tool.execute(steps=[{"title": "Asset discovery"}, {"title": "Report"}])

    assert result == "Plan recorded: 2 steps"


@pytest.mark.asyncio
async def test_write_plan_tool_broadcasts_orchestrator_plan(monkeypatch: pytest.MonkeyPatch):
    channel = MagicMock()
    channel.broadcast_agent_event = AsyncMock(return_value=True)

    class FakeWebSocketChannel:
        @staticmethod
        def get_active_instance():
            return channel

    monkeypatch.setattr("secbot.channels.websocket.WebSocketChannel", FakeWebSocketChannel)
    tool = WritePlanTool(chat_id_getter=lambda: "chat-1")

    result = await tool.execute(
        steps=[
            {"title": "Asset discovery", "detail": "Find live hosts."},
            {"title": "Report", "detail": None},
        ]
    )

    assert result == "Plan recorded: 2 steps"
    channel.broadcast_agent_event.assert_awaited_once()
    kwargs = channel.broadcast_agent_event.await_args.kwargs
    assert kwargs["chat_id"] == "chat-1"
    assert kwargs["type"] == "orchestrator_plan"
    assert kwargs["payload"]["agent"] == "orchestrator"
    assert kwargs["payload"]["steps"] == [
        {"title": "Asset discovery", "detail": "Find live hosts."},
        {"title": "Report"},
    ]

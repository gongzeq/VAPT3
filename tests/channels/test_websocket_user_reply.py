"""WebSocket ``surface_confirm`` + ``scan.user_reply`` envelope tests.

Spec:
  - ``.trellis/spec/backend/high-risk-confirmation.md`` §2.1, §3
  - ``.trellis/spec/backend/websocket-protocol.md`` §4

Exercises:
  - surface_confirm → broadcasts ``high_risk_confirm`` agent_event → await
  - scan.user_reply(approve) → Future resolves True
  - scan.user_reply(deny) → Future resolves False
  - timeout (asyncio.wait_for) → Future cleaned up from _pending_confirms
  - unknown ask_id → error event
  - invalid decision → error event
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from secbot.channels.websocket import WebSocketChannel


def _make_channel() -> WebSocketChannel:
    bus = MagicMock()
    bus.publish_inbound = AsyncMock()
    channel = WebSocketChannel(
        {"enabled": True, "allowFrom": ["*"], "websocketRequiresToken": False},
        bus,
    )
    channel._handle_message = AsyncMock()  # type: ignore[method-assign]
    return channel


@pytest.mark.asyncio
async def test_surface_confirm_approve():
    """Client sends approve → surface_confirm returns True."""
    channel = _make_channel()
    # Spy on broadcast_agent_event to capture the ask_id.
    broadcast_calls: list[dict[str, Any]] = []
    original_broadcast = channel.broadcast_agent_event

    async def _capture_broadcast(**kwargs):
        broadcast_calls.append(kwargs)
        return True

    channel.broadcast_agent_event = _capture_broadcast  # type: ignore[method-assign]

    async def _approve_later():
        """Wait for the pending_confirms entry, then approve."""
        for _ in range(100):
            if channel._pending_confirms:
                break
            await asyncio.sleep(0.01)
        ask_id = next(iter(channel._pending_confirms))
        future = channel._pending_confirms[ask_id]
        future.set_result(True)

    task = asyncio.create_task(_approve_later())
    result = await channel.surface_confirm(
        {"skill": "sqlmap-dump", "summary_for_user": "run SQL injection"},
        chat_id="chat-1",
    )
    await task

    assert result is True
    # Broadcast must have included the payload with ask_id.
    assert len(broadcast_calls) == 1
    assert broadcast_calls[0]["type"] == "high_risk_confirm"
    payload = broadcast_calls[0]["payload"]
    assert "ask_id" in payload
    assert payload["skill"] == "sqlmap-dump"
    # Future should be cleaned up.
    assert not channel._pending_confirms


@pytest.mark.asyncio
async def test_surface_confirm_deny():
    """Client sends deny → surface_confirm returns False."""
    channel = _make_channel()

    async def _deny_later():
        for _ in range(100):
            if channel._pending_confirms:
                break
            await asyncio.sleep(0.01)
        ask_id = next(iter(channel._pending_confirms))
        channel._pending_confirms[ask_id].set_result(False)

    task = asyncio.create_task(_deny_later())
    result = await channel.surface_confirm(
        {"skill": "hydra-bruteforce"},
        chat_id="chat-2",
    )
    await task
    assert result is False
    assert not channel._pending_confirms


@pytest.mark.asyncio
async def test_surface_confirm_timeout_cleanup():
    """Timeout via asyncio.wait_for should NOT leak pending entries."""
    channel = _make_channel()

    # Stub broadcast to prevent real WS sends.
    channel.broadcast_agent_event = AsyncMock(return_value=True)  # type: ignore[method-assign]

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(
            channel.surface_confirm({"skill": "x"}, chat_id="c"),
            timeout=0.05,
        )

    # The finally clause should have popped the entry.
    assert not channel._pending_confirms


@pytest.mark.asyncio
async def test_dispatch_scan_user_reply_approve():
    """Full round-trip via _dispatch_envelope(scan.user_reply)."""
    channel = _make_channel()
    channel.broadcast_agent_event = AsyncMock(return_value=True)  # type: ignore[method-assign]
    mock_conn = AsyncMock()

    async def _reply_approve():
        for _ in range(100):
            if channel._pending_confirms:
                break
            await asyncio.sleep(0.01)
        ask_id = next(iter(channel._pending_confirms))
        envelope = {"type": "scan.user_reply", "ask_id": ask_id, "decision": "approve"}
        await channel._dispatch_envelope(mock_conn, "client-1", envelope)

    task = asyncio.create_task(_reply_approve())
    result = await channel.surface_confirm(
        {"skill": "sqlmap-dump"},
        chat_id="chat-1",
    )
    await task
    assert result is True


@pytest.mark.asyncio
async def test_dispatch_scan_user_reply_deny():
    """Full round-trip via _dispatch_envelope(scan.user_reply) with deny."""
    channel = _make_channel()
    channel.broadcast_agent_event = AsyncMock(return_value=True)  # type: ignore[method-assign]
    mock_conn = AsyncMock()

    async def _reply_deny():
        for _ in range(100):
            if channel._pending_confirms:
                break
            await asyncio.sleep(0.01)
        ask_id = next(iter(channel._pending_confirms))
        envelope = {"type": "scan.user_reply", "ask_id": ask_id, "decision": "deny"}
        await channel._dispatch_envelope(mock_conn, "client-1", envelope)

    task = asyncio.create_task(_reply_deny())
    result = await channel.surface_confirm(
        {"skill": "hydra-bruteforce"},
        chat_id="chat-2",
    )
    await task
    assert result is False


@pytest.mark.asyncio
async def test_dispatch_scan_user_reply_unknown_ask_id():
    """Reply with non-existent ask_id → error event back to client."""
    channel = _make_channel()
    mock_conn = AsyncMock()

    envelope = {"type": "scan.user_reply", "ask_id": "nonexist", "decision": "approve"}
    await channel._dispatch_envelope(mock_conn, "client-1", envelope)

    # Should send an error event
    mock_conn.send.assert_awaited_once()
    sent = json.loads(mock_conn.send.call_args[0][0])
    assert sent["event"] == "error"
    assert sent["detail"] == "unknown ask_id"


@pytest.mark.asyncio
async def test_dispatch_scan_user_reply_invalid_decision():
    """Reply with invalid decision → error event."""
    channel = _make_channel()
    mock_conn = AsyncMock()

    # Register a real pending confirm so ask_id is valid.
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    channel._pending_confirms["real-ask"] = future

    envelope = {"type": "scan.user_reply", "ask_id": "real-ask", "decision": "maybe"}
    await channel._dispatch_envelope(mock_conn, "client-1", envelope)

    mock_conn.send.assert_awaited_once()
    sent = json.loads(mock_conn.send.call_args[0][0])
    assert sent["event"] == "error"
    assert sent["detail"] == "invalid decision"
    # Future should NOT have been resolved.
    assert not future.done()
    future.cancel()  # cleanup


@pytest.mark.asyncio
async def test_dispatch_scan_user_reply_missing_ask_id():
    """Reply without ask_id → error event."""
    channel = _make_channel()
    mock_conn = AsyncMock()

    envelope = {"type": "scan.user_reply", "decision": "approve"}
    await channel._dispatch_envelope(mock_conn, "client-1", envelope)

    mock_conn.send.assert_awaited_once()
    sent = json.loads(mock_conn.send.call_args[0][0])
    assert sent["event"] == "error"
    assert sent["detail"] == "missing ask_id"


@pytest.mark.asyncio
async def test_stop_cancels_pending_confirms():
    """Channel.stop() should cancel all pending futures."""
    channel = _make_channel()
    channel._running = True
    loop = asyncio.get_running_loop()
    f1 = loop.create_future()
    f2 = loop.create_future()
    channel._pending_confirms = {"a": f1, "b": f2}

    await channel.stop()

    assert f1.cancelled()
    assert f2.cancelled()
    assert not channel._pending_confirms

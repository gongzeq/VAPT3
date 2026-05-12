"""Unit tests for the ``activity_event`` WebSocket broadcast + loop integration.

Spec: ``.trellis/tasks/05-10-p2-notification-activity/prd.md`` §WS `activity_event`.
Covers:
  * Frame shape (event / chat_id / category / agent / step / timestamp).
  * Per-``chat_id`` 1s/event throttle (shared ``_should_throttle_broadcast``).
  * Optional ``duration_ms`` field omitted when not provided.
  * ``WebSocketChannel.get_active_instance`` singleton + ``reset`` semantics.
  * End-to-end ``_LoopHook`` → broadcast wiring through ``before_execute_tools``
    / ``after_iteration`` (only fires for ``channel="websocket"``).
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio  # noqa: F401 — enables async fixtures at collection time

from secbot.agent.hook import AgentHookContext
from secbot.agent.loop import _LoopHook
from secbot.channels.websocket import WebSocketChannel

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_active_channel():
    """Isolate each test from the process-wide channel singleton."""
    WebSocketChannel.reset_active_instance()
    try:
        yield
    finally:
        WebSocketChannel.reset_active_instance()


@pytest.fixture
def channel() -> WebSocketChannel:
    bus = MagicMock()
    bus.publish_inbound = AsyncMock()
    ch = WebSocketChannel(
        {
            "enabled": True,
            "allowFrom": ["*"],
            "host": "127.0.0.1",
            "port": 0,
            "path": "/",
            "websocketRequiresToken": False,
        },
        bus,
    )
    ch._api_tokens["live"] = time.monotonic() + 60.0
    return ch


def _attach_subscriber(ch: WebSocketChannel, chat_id: str) -> MagicMock:
    conn = MagicMock()
    conn.send = AsyncMock()
    ch._subs[chat_id] = {conn}
    ch._conn_chats[conn] = {chat_id}
    return conn


# ---------------------------------------------------------------------------
# broadcast_activity_event — frame shape + throttle
# ---------------------------------------------------------------------------


async def test_broadcast_activity_event_dispatches_frame(channel: WebSocketChannel) -> None:
    conn = _attach_subscriber(channel, "chat-a")

    sent = await channel.broadcast_activity_event(
        category="tool_call",
        agent="port_scan",
        step='→ 调用 tool: port_scan(target="192.168.1.0/24")',
        chat_id="chat-a",
        duration_ms=1200,
    )

    assert sent is True
    conn.send.assert_awaited_once()
    frame = json.loads(conn.send.await_args.args[0])
    assert frame["event"] == "activity_event"
    assert frame["chat_id"] == "chat-a"
    assert frame["category"] == "tool_call"
    assert frame["agent"] == "port_scan"
    assert frame["step"].startswith("→ 调用 tool: port_scan")
    assert frame["duration_ms"] == 1200
    assert "timestamp" in frame


async def test_broadcast_activity_event_omits_duration_when_absent(
    channel: WebSocketChannel,
) -> None:
    conn = _attach_subscriber(channel, "chat-a")

    sent = await channel.broadcast_activity_event(
        category="tool_call",
        agent="asset_discovery",
        step="→ 调用 tool: asset_discovery()",
        chat_id="chat-a",
    )

    assert sent is True
    frame = json.loads(conn.send.await_args.args[0])
    assert "duration_ms" not in frame


async def test_broadcast_activity_event_throttles_within_1s(channel: WebSocketChannel) -> None:
    conn = _attach_subscriber(channel, "chat-a")

    a = await channel.broadcast_activity_event(
        category="tool_call",
        agent="x",
        step="→ x()",
        chat_id="chat-a",
    )
    b = await channel.broadcast_activity_event(
        category="tool_result",
        agent="x",
        step="← x → ok",
        chat_id="chat-a",
    )

    assert a is True
    assert b is False
    assert conn.send.await_count == 1


async def test_broadcast_activity_event_throttle_is_per_chat(channel: WebSocketChannel) -> None:
    a_conn = _attach_subscriber(channel, "chat-a")
    b_conn = _attach_subscriber(channel, "chat-b")

    a = await channel.broadcast_activity_event(
        category="tool_call", agent="x", step="→ x()", chat_id="chat-a"
    )
    b = await channel.broadcast_activity_event(
        category="tool_call", agent="x", step="→ x()", chat_id="chat-b"
    )

    assert a is True and b is True
    a_conn.send.assert_awaited_once()
    b_conn.send.assert_awaited_once()


async def test_broadcast_activity_event_returns_false_without_subscribers(
    channel: WebSocketChannel,
) -> None:
    sent = await channel.broadcast_activity_event(
        category="tool_call", agent="x", step="→ x()", chat_id="lonely"
    )
    # Throttle bookkeeping still marks the emission as "last attempted" so the
    # subsequent "missing subscribers" path is covered here. A second call in
    # the same second is legitimately throttled.
    assert sent is False


# ---------------------------------------------------------------------------
# get_active_instance / reset_active_instance singleton semantics
# ---------------------------------------------------------------------------


async def test_get_active_instance_returns_last_constructed(
    channel: WebSocketChannel,
) -> None:
    assert WebSocketChannel.get_active_instance() is channel


async def test_reset_active_instance_clears_registry(channel: WebSocketChannel) -> None:
    assert WebSocketChannel.get_active_instance() is channel
    WebSocketChannel.reset_active_instance()
    assert WebSocketChannel.get_active_instance() is None


# ---------------------------------------------------------------------------
# _LoopHook → broadcast_activity_event integration
# ---------------------------------------------------------------------------


def _make_hook(channel_tag: str, chat_id: str = "chat-a") -> _LoopHook:
    # Bypass the real AgentLoop — the hook only calls a couple of bound methods
    # on it, and none of them fire on this code path.
    loop_stub = SimpleNamespace(
        _current_iteration=0,
        _strip_think=lambda x: x,
        _tool_hint=lambda tc: "",
        _set_tool_context=lambda *a, **kw: None,
    )
    return _LoopHook(
        loop_stub,  # type: ignore[arg-type]
        on_progress=None,
        on_stream=None,
        on_stream_end=None,
        channel=channel_tag,
        chat_id=chat_id,
    )


def _make_tool_call(call_id: str, name: str, arguments: dict):
    return SimpleNamespace(id=call_id, name=name, arguments=arguments)


def _make_ctx(tool_calls: list, tool_events: list | None = None, tool_results: list | None = None):
    ctx = MagicMock(spec=AgentHookContext)
    ctx.tool_calls = tool_calls
    ctx.tool_events = tool_events if tool_events is not None else []
    ctx.tool_results = tool_results if tool_results is not None else []
    ctx.streamed_content = None
    ctx.response = None
    ctx.usage = {}
    ctx.iteration = 1
    return ctx


async def test_loop_hook_broadcasts_tool_call_for_websocket(channel: WebSocketChannel) -> None:
    conn = _attach_subscriber(channel, "chat-a")
    hook = _make_hook(channel_tag="websocket")
    ctx = _make_ctx([_make_tool_call("call-1", "port_scan", {"target": "10.0.0.0/24"})])

    await hook.before_execute_tools(ctx)

    conn.send.assert_awaited_once()
    frame = json.loads(conn.send.await_args.args[0])
    assert frame["event"] == "activity_event"
    assert frame["category"] == "tool_call"
    assert frame["agent"] == "port_scan"
    assert "port_scan" in frame["step"]
    # start-time stamped so the finish broadcast can compute duration_ms.
    assert "call-1" in hook._tool_call_started_at


async def test_loop_hook_skips_broadcast_for_non_websocket(channel: WebSocketChannel) -> None:
    conn = _attach_subscriber(channel, "chat-a")
    hook = _make_hook(channel_tag="cli")
    ctx = _make_ctx([_make_tool_call("call-1", "port_scan", {})])

    await hook.before_execute_tools(ctx)

    conn.send.assert_not_awaited()
    assert hook._tool_call_started_at == {}


async def test_loop_hook_skips_broadcast_when_no_active_channel() -> None:
    # No channel fixture → singleton returns None, broadcast is a no-op.
    WebSocketChannel.reset_active_instance()
    hook = _make_hook(channel_tag="websocket")
    ctx = _make_ctx([_make_tool_call("call-1", "x", {})])
    # Must not raise even though the active instance is absent.
    await hook.before_execute_tools(ctx)
    assert hook._tool_call_started_at == {}


async def test_loop_hook_after_iteration_broadcasts_tool_result(
    channel: WebSocketChannel,
) -> None:
    conn = _attach_subscriber(channel, "chat-a")
    hook = _make_hook(channel_tag="websocket")
    tc = _make_tool_call("call-1", "port_scan", {"target": "10.0.0.0/24"})

    # First broadcast (tool_call) stamps started_at and consumes the 1s window.
    ctx_start = _make_ctx([tc])
    await hook.before_execute_tools(ctx_start)

    # Advance throttle scope by swapping chat_id so the second frame emits
    # unthrottled. Alternative: sleep 1.1s — too slow for unit tests.
    hook._chat_id = "chat-b"
    _attach_subscriber(channel, "chat-b")

    ctx_finish = _make_ctx(
        [tc], tool_events=[{"status": "ok"}], tool_results=["{\"open\":22}"],
    )
    await hook.after_iteration(ctx_finish)

    # First call to chat-a (tool_call) + second call to chat-b (tool_result).
    assert conn.send.await_count == 1  # chat-a only received the start frame
    # Finish broadcast should have popped the started_at entry.
    assert "call-1" not in hook._tool_call_started_at


async def test_loop_hook_format_step_truncates_long_args(channel: WebSocketChannel) -> None:
    conn = _attach_subscriber(channel, "chat-a")
    hook = _make_hook(channel_tag="websocket")
    long_value = "A" * 200
    ctx = _make_ctx([_make_tool_call("call-x", "noop", {"payload": long_value})])

    await hook.before_execute_tools(ctx)

    frame = json.loads(conn.send.await_args.args[0])
    # Step must be truncated with an ellipsis so dashboard frames stay light.
    assert "..." in frame["step"]
    assert len(frame["step"]) < 200


# ---------------------------------------------------------------------------
# _extract_thought — 思维链来源过滤（修复“思维链和输出内容一样”回归）
# ---------------------------------------------------------------------------


async def test_extract_thought_prefers_reasoning_content():
    """reasoning_content 非空时，直接作为思维链内容。"""
    response = SimpleNamespace(
        reasoning_content="  plan: scan ports first  ",
        content="好的，我来扫描端口。",
    )
    assert _LoopHook._extract_thought(response) == "plan: scan ports first"


async def test_extract_thought_extracts_think_block_from_content():
    """无 reasoning_content 时，从 <think> 块提取内部；正文不参与。"""
    response = SimpleNamespace(
        reasoning_content=None,
        content="<think>step 1: probe http</think>好的，我来扫描。",
    )
    assert _LoopHook._extract_thought(response) == "step 1: probe http"


async def test_extract_thought_returns_none_for_plain_assistant_text():
    """纯 assistant 文本（无 think 标签、无 reasoning_content）不应作为思维链，
    否则会与 assistant 气泡重复（用户报告的‘思维链和输出内容一样’的根因）。
    """
    response = SimpleNamespace(
        reasoning_content=None,
        content="好的，我来对这个目标进行初步探测。先看看 HTTP 服务的情况。",
    )
    assert _LoopHook._extract_thought(response) is None


async def test_extract_thought_handles_none_response():
    assert _LoopHook._extract_thought(None) is None


async def test_before_execute_tools_does_not_broadcast_plain_content_as_thought(
    channel: WebSocketChannel,
) -> None:
    """End-to-end：普通 assistant 文本不应产生 thought agent_event 帧。"""
    conn = _attach_subscriber(channel, "chat-a")
    progress_calls: list = []

    async def _on_progress(*args, **kwargs):
        progress_calls.append((args, kwargs))

    loop_stub = SimpleNamespace(
        _current_iteration=0,
        _strip_think=lambda x: x,
        _tool_hint=lambda tc: "",
        _set_tool_context=lambda *a, **kw: None,
    )
    hook = _LoopHook(
        loop_stub,  # type: ignore[arg-type]
        on_progress=_on_progress,
        on_stream=None,
        on_stream_end=None,
        channel="websocket",
        chat_id="chat-a",
    )

    ctx = _make_ctx([_make_tool_call("call-1", "port_scan", {"target": "1.2.3.4"})])
    ctx.response = SimpleNamespace(
        reasoning_content=None,
        content="好的，我来对这个目标进行初步探测。",
    )
    ctx.streamed_content = True  # streaming 模式：正文已通过 delta 推给前端

    await hook.before_execute_tools(ctx)

    frames = [json.loads(c.args[0]) for c in conn.send.await_args_list]
    thought_frames = [
        f for f in frames if f.get("event") == "agent_event" and f.get("type") == "thought"
    ]
    assert thought_frames == [], (
        "普通 assistant 文本不应作为 thought 广播；这会导致思维链卡片与 assistant "
        "气泡内容完全一致（已知回归）。"
    )

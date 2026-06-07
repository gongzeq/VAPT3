"""Agent turn streaming and event hook implementation."""

from __future__ import annotations

import json
import os
import re
import time
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

from secbot.agent.hook import AgentHook, AgentHookContext
from secbot.utils.progress_events import (
    build_tool_event_finish_payloads,
    build_tool_event_start_payload,
    invoke_on_progress,
    on_progress_accepts_tool_events,
)

if TYPE_CHECKING:
    from secbot.agent.loop import AgentLoop


class TurnEventHook(AgentHook):
    """Hook that streams turn text and emits Surface-facing turn events."""

    def __init__(
        self,
        agent_loop: AgentLoop,
        on_progress: Callable[..., Awaitable[None]] | None = None,
        on_stream: Callable[[str], Awaitable[None]] | None = None,
        on_stream_end: Callable[..., Awaitable[None]] | None = None,
        *,
        channel: str = "cli",
        chat_id: str = "direct",
        message_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        session_key: str | None = None,
    ) -> None:
        super().__init__(reraise=True)
        self._loop = agent_loop
        self._on_progress = on_progress
        self._on_stream = on_stream
        self._on_stream_end = on_stream_end
        self._channel = channel
        self._chat_id = chat_id
        self._message_id = message_id
        self._metadata = metadata or {}
        self._session_key = session_key
        self._stream_buf = ""
        # Track tool-call start timestamps so ``after_iteration`` can compute a
        # duration_ms for the ``activity_event`` WS broadcast. Keyed on
        # ``call_id`` so concurrent tool calls in the same iteration don't
        # overwrite each other. Only populated when the originating channel
        # is ``"websocket"`` since that's the sole consumer today.
        self._tool_call_started_at: dict[str, float] = {}

    def wants_streaming(self) -> bool:
        return self._on_stream is not None

    async def on_stream(self, context: AgentHookContext, delta: str) -> None:
        from secbot.utils.helpers import strip_think

        prev_clean = strip_think(self._stream_buf)
        self._stream_buf += delta
        new_clean = strip_think(self._stream_buf)
        incremental = new_clean[len(prev_clean) :]
        if incremental and self._on_stream:
            await self._on_stream(incremental)

    async def on_stream_end(self, context: AgentHookContext, *, resuming: bool) -> None:
        if self._on_stream_end:
            await self._on_stream_end(resuming=resuming)
        self._stream_buf = ""

    async def before_iteration(self, context: AgentHookContext) -> None:
        self._loop._current_iteration = context.iteration
        logger.debug(
            "Starting agent loop iteration {} for session {}",
            context.iteration,
            self._session_key,
        )

    @staticmethod
    def _extract_thought(response: Any) -> str | None:
        """Derive the thought-card text from an LLM response.

        Only returns content that should not appear in the assistant bubble,
        avoiding duplicate thought and answer text.
        """
        if response is None:
            return None
        reasoning = getattr(response, "reasoning_content", None)
        if isinstance(reasoning, str) and reasoning.strip():
            return reasoning.strip()
        content = getattr(response, "content", None)
        if isinstance(content, str):
            # Capture the FIRST complete <think>...</think> block (or
            # <thought>...</thought>); trailing/unclosed blocks are ignored.
            match = re.search(r"<think>([\s\S]*?)</think>", content)
            if match is None:
                match = re.search(r"<thought>([\s\S]*?)</thought>", content)
            if match is not None:
                inner = match.group(1).strip()
                if inner:
                    return inner
        return None

    async def _broadcast_agent_thought(self, thought: str) -> None:
        """Emit a ``thought`` agent_event frame for the chat surface."""
        if self._channel != "websocket":
            return
        from secbot.channels.websocket import WebSocketChannel

        channel = WebSocketChannel.get_active_instance()
        if channel is None:
            return
        try:
            await channel.broadcast_agent_event(
                chat_id=self._chat_id,
                type="thought",
                payload={"agent": "orchestrator", "content": thought},
            )
        except Exception:
            logger.debug("agent_event (thought) broadcast failed", exc_info=True)

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        if self._on_progress:
            # Legacy progress trace: non-streaming channels need visible
            # assistant text before tool calls. Streaming channels already
            # received it via deltas, so skip to avoid duplicates.
            if not self._on_stream and not context.streamed_content:
                visible = self._loop._strip_think(
                    context.response.content if context.response else None
                )
                if visible:
                    await self._on_progress(visible)
            thought = self._extract_thought(context.response)
            if thought:
                await self._broadcast_agent_thought(thought)
            tool_hint = self._loop._strip_think(self._loop._tool_hint(context.tool_calls))
            tool_events = [build_tool_event_start_payload(tc) for tc in context.tool_calls]
            await invoke_on_progress(
                self._on_progress,
                tool_hint,
                tool_hint=True,
                tool_events=tool_events,
            )
        for tc in context.tool_calls:
            args_str = json.dumps(tc.arguments, ensure_ascii=False)
            logger.info("Tool call: {}({})", tc.name, args_str[:200])
        self._loop._set_tool_context(
            self._channel,
            self._chat_id,
            self._message_id,
            self._metadata,
            session_key=self._session_key,
        )
        # Broadcast ``activity_event`` frames so the Dashboard activity stream
        # mirrors tool invocations in near real-time. Broadcast is best-effort
        # and never blocks tool execution.
        if self._channel == "websocket" and context.tool_calls:
            await self._broadcast_activity_tool_calls(context.tool_calls)

    async def _broadcast_activity_tool_calls(self, tool_calls: list[Any]) -> None:
        """Emit one ``tool_call`` activity_event per tool call + stamp start time."""
        from secbot.channels.websocket import WebSocketChannel

        channel = WebSocketChannel.get_active_instance()
        if channel is None:
            return
        now = time.monotonic()
        for tc in tool_calls:
            call_id = str(getattr(tc, "id", "") or "")
            if call_id:
                self._tool_call_started_at[call_id] = now
            name = getattr(tc, "name", "") or "tool"
            args = getattr(tc, "arguments", {}) or {}
            step = self._format_activity_step(name, args)
            try:
                await channel.broadcast_activity_event(
                    category="tool_call",
                    agent=name,
                    step=step,
                    chat_id=self._chat_id,
                )
            except Exception:
                logger.debug("activity_event (start) broadcast failed", exc_info=True)

    @staticmethod
    def _format_activity_step(name: str, arguments: dict[str, Any]) -> str:
        """Render ``-> call tool: name(k=v, ...)`` with bounded arguments."""
        if not isinstance(arguments, dict) or not arguments:
            return f"→ 调用 tool: {name}()"
        parts: list[str] = []
        for k, v in arguments.items():
            try:
                rendered = json.dumps(v, ensure_ascii=False)
            except Exception:
                rendered = str(v)
            if len(rendered) > 80:
                rendered = rendered[:77] + "..."
            parts.append(f"{k}={rendered}")
        return f"→ 调用 tool: {name}({', '.join(parts)})"

    async def _broadcast_activity_tool_results(self, context: AgentHookContext) -> None:
        """Emit one ``tool_result`` activity_event per finished tool call."""
        from secbot.channels.websocket import WebSocketChannel

        channel = WebSocketChannel.get_active_instance()
        if channel is None:
            return
        now = time.monotonic()
        count = min(len(context.tool_calls), len(context.tool_events))
        for idx in range(count):
            tc = context.tool_calls[idx]
            event = context.tool_events[idx] if isinstance(context.tool_events[idx], dict) else {}
            status = event.get("status")
            call_id = str(getattr(tc, "id", "") or "")
            started_at = self._tool_call_started_at.pop(call_id, None) if call_id else None
            duration_ms: int | None = (
                int((now - started_at) * 1000) if started_at is not None else None
            )
            name = getattr(tc, "name", "") or "tool"
            suffix = "ok" if status == "ok" else (status or "error")
            step = f"← {name} → {suffix}"
            try:
                await channel.broadcast_activity_event(
                    category="tool_result",
                    agent=name,
                    step=step,
                    chat_id=self._chat_id,
                    duration_ms=duration_ms,
                )
            except Exception:
                logger.debug("activity_event (finish) broadcast failed", exc_info=True)

    async def after_iteration(self, context: AgentHookContext) -> None:
        if (
            self._on_progress
            and context.tool_calls
            and context.tool_events
            and on_progress_accepts_tool_events(self._on_progress)
        ):
            tool_events = build_tool_event_finish_payloads(context)
            if tool_events:
                await invoke_on_progress(
                    self._on_progress,
                    "",
                    tool_hint=False,
                    tool_events=tool_events,
                )
        if self._channel == "websocket" and context.tool_calls and context.tool_events:
            await self._broadcast_activity_tool_results(context)
        usage = context.usage or {}
        logger.debug(
            "LLM usage: prompt={} completion={} cached={}",
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0),
            usage.get("cached_tokens", 0),
        )

    def finalize_content(self, context: AgentHookContext, content: str | None) -> str | None:
        return self._loop._strip_think(content)


def _extract_report_media(
    all_msgs: list[dict[str, Any]], final_content: str
) -> list[str]:
    """Scan tool results and final content for report file paths.

    Looks for ``report_path`` entries in JSON tool results and for
    ``.html`` file paths mentioned in the assistant's final reply.
    Only returns paths that actually exist on disk.
    """
    paths: set[str] = set()

    for message in all_msgs:
        if message.get("role") != "tool":
            continue
        content = message.get("content", "")
        if not isinstance(content, str):
            continue
        for match in re.finditer(r'"report_path"\s*:\s*"([^"]+)"', content):
            path = match.group(1)
            if path and path != "null" and os.path.isfile(path):
                paths.add(path)

    for match in re.finditer(r"[\w/\\._-]+\.html", final_content):
        path = match.group(0)
        if os.path.isabs(path) and os.path.isfile(path):
            paths.add(path)

    return sorted(paths)

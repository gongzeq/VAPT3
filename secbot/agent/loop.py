"""Agent loop: the core processing engine."""

from __future__ import annotations

import asyncio
import dataclasses
import os
import time
from contextlib import AsyncExitStack, nullcontext, suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

from secbot.agent.asset_feed import AssetFeed, AssetFeedRegistry
from secbot.agent.autocompact import AutoCompact
from secbot.agent.blackboard import Blackboard, BlackboardRegistry
from secbot.agent.context import ContextBuilder
from secbot.agent.hook import AgentHook, CompositeHook
from secbot.agent.memory import Consolidator, Dream
from secbot.agent.runner import _MAX_INJECTIONS_PER_TURN, AgentRunner, AgentRunSpec
from secbot.agent.skills import BUILTIN_SKILLS_DIR
from secbot.agent.subagent import SubagentManager
from secbot.agent.tools.approval import RequestApprovalTool
from secbot.agent.tools.ask import (
    AskUserTool,
    ask_user_options_from_messages,
    ask_user_outbound,
    ask_user_tool_result_messages,
    pending_ask_user_call,
)
from secbot.agent.tools.asset_feed import AssetPushTool, ReadAssetsTool
from secbot.agent.tools.blackboard import BlackboardReadTool, BlackboardWriteTool
from secbot.agent.tools.cron import CronTool
from secbot.agent.tools.curl import CurlTool
from secbot.agent.tools.file_state import FileStateStore, bind_file_states, reset_file_states
from secbot.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from secbot.agent.tools.message import MessageTool
from secbot.agent.tools.notebook import NotebookEditTool
from secbot.agent.tools.plan import WritePlanTool
from secbot.agent.tools.registry import ToolRegistry
from secbot.agent.tools.search import GlobTool, GrepTool
from secbot.agent.tools.self import MyTool

# NOTE: ExecTool intentionally not imported here. ExecTool is hard-disabled —
# all shell access for security workflows MUST go through SkillTool. See
# _register_operational_tools and subagent.py for the matching policy.
from secbot.agent.tools.skill import bind_skill_context, discover_skill_tools
from secbot.agent.tools.spawn import SpawnTool
from secbot.agent.turn_events import TurnEventHook, _extract_report_media
from secbot.agents.high_risk import HighRiskGate
from secbot.bus.events import InboundMessage, OutboundMessage
from secbot.bus.queue import MessageBus
from secbot.command import CommandContext, CommandRouter, register_builtin_commands
from secbot.config.schema import AgentDefaults
from secbot.providers.base import LLMProvider
from secbot.providers.factory import ProviderSnapshot
from secbot.session.manager import Session, SessionManager
from secbot.utils.document import extract_documents
from secbot.utils.helpers import image_placeholder_text
from secbot.utils.helpers import truncate_text as truncate_text_fn
from secbot.utils.runtime import EMPTY_FINAL_RESPONSE_MESSAGE
from secbot.utils.webui_titles import mark_webui_session, maybe_generate_webui_title_after_turn

if TYPE_CHECKING:
    from secbot.config.schema import ChannelsConfig, ExecToolConfig, ToolsConfig, WebToolsConfig
    from secbot.cron.service import CronService


UNIFIED_SESSION_KEY = "unified:default"


_LoopHook = TurnEventHook


class AgentLoop:
    """
    The agent loop is the core processing engine.

    It:
    1. Receives messages from the bus
    2. Builds context with history, memory, skills
    3. Calls the LLM
    4. Executes tool calls
    5. Sends responses back
    """

    _RUNTIME_CHECKPOINT_KEY = "runtime_checkpoint"
    _PENDING_USER_TURN_KEY = "pending_user_turn"

    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        max_iterations: int | None = None,
        context_window_tokens: int | None = None,
        context_block_limit: int | None = None,
        max_tool_result_chars: int | None = None,
        provider_retry_mode: str = "standard",
        tool_hint_max_length: int | None = None,
        web_config: WebToolsConfig | None = None,
        exec_config: ExecToolConfig | None = None,
        cron_service: CronService | None = None,
        restrict_to_workspace: bool = False,
        session_manager: SessionManager | None = None,
        mcp_servers: dict | None = None,
        channels_config: ChannelsConfig | None = None,
        timezone: str | None = None,
        session_ttl_minutes: int = 0,
        consolidation_ratio: float = 0.5,
        max_messages: int = 120,
        hooks: list[AgentHook] | None = None,
        unified_session: bool = False,
        disabled_skills: list[str] | None = None,
        tools_config: ToolsConfig | None = None,
        provider_snapshot_loader: Callable[[], ProviderSnapshot] | None = None,
        provider_signature: tuple[object, ...] | None = None,
        is_orchestrator: bool = True,
    ):
        from secbot.config.schema import ExecToolConfig, ToolsConfig, WebToolsConfig

        _tc = tools_config or ToolsConfig()
        defaults = AgentDefaults()
        self.bus = bus
        self.channels_config = channels_config
        self.provider = provider
        self._provider_snapshot_loader = provider_snapshot_loader
        self._provider_signature = provider_signature
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.max_iterations = (
            max_iterations if max_iterations is not None else defaults.max_tool_iterations
        )
        self.context_window_tokens = (
            context_window_tokens
            if context_window_tokens is not None
            else defaults.context_window_tokens
        )
        self.context_block_limit = context_block_limit
        self.max_tool_result_chars = (
            max_tool_result_chars
            if max_tool_result_chars is not None
            else defaults.max_tool_result_chars
        )
        self.provider_retry_mode = provider_retry_mode
        self.tool_hint_max_length = (
            tool_hint_max_length if tool_hint_max_length is not None
            else defaults.tool_hint_max_length
        )
        self.web_config = web_config or WebToolsConfig()
        self.exec_config = exec_config or ExecToolConfig()
        self.cron_service = cron_service
        self.restrict_to_workspace = restrict_to_workspace
        self._start_time = time.time()
        self._last_usage: dict[str, int] = {}
        self._extra_hooks: list[AgentHook] = hooks or []
        self.is_orchestrator = is_orchestrator
        self._current_chat_id: str | None = None

        self.context = ContextBuilder(workspace, timezone=timezone, disabled_skills=disabled_skills)
        self.sessions = session_manager or SessionManager(workspace)
        self.tools = ToolRegistry()
        # One file-read/write tracker per logical session. The tool registry is
        # shared by this loop, so tools resolve the active state via contextvars.
        self._file_state_store = FileStateStore()
        self.runner = AgentRunner(provider)
        # Per-chat shared blackboards — owned by a process-wide registry so a
        # page refresh (``GET /api/blackboard?chat_id=...``) can recover
        # entries appended across previous turns. ``self.blackboard`` is kept
        # as the *active* per-turn pointer for legacy callers (orchestrator
        # tools register against it at __init__ time before chat_id is known);
        # ``_run_agent_loop`` rebinds it from the registry on every turn.
        # ``on_write`` is bound per-turn in _run_agent_loop when channel == "websocket".
        self.blackboard_registry = BlackboardRegistry()
        self.blackboard = Blackboard()
        # PR-1 (asset-feed): chat-scoped real-time discovery channel,
        # complementary to (and decoupled from) the blackboard. The
        # blackboard is for aggregated summaries; the asset feed is for
        # one entry per discrete asset push, with orchestrator wake-up.
        self.asset_feed_registry = AssetFeedRegistry()
        # Active per-turn asset feed pointer (rebound in ``_run_agent_loop``).
        # Initialised to a default feed so tools registered with a
        # ``lambda: self.asset_feed`` callable always resolve to a valid
        # instance even before the first turn rebinds it.
        self.asset_feed: AssetFeed = AssetFeed()
        # PR3: lazy-load the expert-agent registry so SpawnTool can validate
        # ``agent=`` and SubagentManager can filter scoped skills. A broken
        # YAML MUST NOT crash the loop — we log and fall through to ``None``,
        # in which case ``spawn(agent=...)`` returns a user-readable error.
        try:
            from secbot.agents.registry import load_agent_registry

            agents_dir = Path(__file__).resolve().parents[1] / "agents"
            self._agent_registry = (
                load_agent_registry(
                    agents_dir,
                    skill_names=None,
                    skills_root=BUILTIN_SKILLS_DIR if BUILTIN_SKILLS_DIR.is_dir() else None,
                    skill_binary_overrides=dict(_tc.skill_binaries or {}),
                )
                if agents_dir.is_dir()
                else None
            )
        except Exception:
            logger.exception("failed to load expert-agent registry; spawn(agent=...) will error")
            self._agent_registry = None
        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            model=self.model,
            web_config=self.web_config,
            max_tool_result_chars=self.max_tool_result_chars,
            exec_config=self.exec_config,
            restrict_to_workspace=restrict_to_workspace,
            disabled_skills=disabled_skills,
            max_iterations=self.max_iterations,
            agent_registry=self._agent_registry,
            blackboard=self.blackboard,
            blackboard_registry=self.blackboard_registry,
            asset_feed_registry=self.asset_feed_registry,
            parent_result_callback=self._route_subagent_result_to_pending,
        )
        self._unified_session = unified_session
        self._max_messages = max_messages if max_messages > 0 else 120
        self._running = False
        self._mcp_servers = mcp_servers or {}
        self._mcp_stacks: dict[str, AsyncExitStack] = {}
        self._mcp_connected = False
        self._mcp_connecting = False
        self._active_tasks: dict[str, list[asyncio.Task]] = {}  # session_key -> tasks
        self._background_tasks: list[asyncio.Task] = []
        self._session_locks: dict[str, asyncio.Lock] = {}
        # Shared high-risk gate for all SkillTool instances — ensures the audit
        # trail is centralised per loop (and therefore per scan).
        self._high_risk_gate = HighRiskGate()
        # Per-session pending queues for mid-turn message injection.
        # When a session has an active task, new messages for that session
        # are routed here instead of creating a new task.
        self._pending_queues: dict[str, asyncio.Queue] = {}
        # SECBOT_MAX_CONCURRENT_REQUESTS: <=0 means unlimited; default 3.
        _max = int(os.environ.get("SECBOT_MAX_CONCURRENT_REQUESTS", "3"))
        self._concurrency_gate: asyncio.Semaphore | None = (
            asyncio.Semaphore(_max) if _max > 0 else None
        )
        self.consolidator = Consolidator(
            store=self.context.memory,
            provider=provider,
            model=self.model,
            sessions=self.sessions,
            context_window_tokens=self.context_window_tokens,
            build_messages=self.context.build_messages,
            get_tool_definitions=self.tools.get_definitions,
            max_completion_tokens=provider.generation.max_tokens,
            consolidation_ratio=consolidation_ratio,
        )
        self.auto_compact = AutoCompact(
            sessions=self.sessions,
            consolidator=self.consolidator,
            session_ttl_minutes=session_ttl_minutes,
        )
        self.dream = Dream(
            store=self.context.memory,
            provider=provider,
            model=self.model,
        )
        self._register_default_tools()
        if not self.is_orchestrator and _tc.my.enable:
            self.tools.register(MyTool(loop=self, modify_allowed=_tc.my.allow_set))
        self._runtime_vars: dict[str, Any] = {}
        self._current_iteration: int = 0
        self.commands = CommandRouter()
        register_builtin_commands(self.commands)

    def _sync_subagent_runtime_limits(self) -> None:
        """Keep subagent runtime limits aligned with mutable loop settings."""
        self.subagents.max_iterations = self.max_iterations

    async def _route_subagent_result_to_pending(self, msg: InboundMessage) -> bool:
        """Deliver a subagent result directly to an active parent turn if possible."""
        effective_key = self._effective_session_key(msg)
        queue = self._pending_queues.get(effective_key)
        if queue is None:
            return False
        pending_msg = msg
        if effective_key != msg.session_key:
            pending_msg = dataclasses.replace(
                msg,
                session_key_override=effective_key,
            )
        try:
            queue.put_nowait(pending_msg)
        except asyncio.QueueFull:
            logger.warning(
                "Pending queue full for session {}, falling back to queued subagent result",
                effective_key,
            )
            return False
        logger.info("Routed subagent result directly to pending queue for session {}", effective_key)
        return True

    def _apply_provider_snapshot(self, snapshot: ProviderSnapshot) -> None:
        """Swap model/provider for future turns without disturbing an active one."""
        provider = snapshot.provider
        model = snapshot.model
        context_window_tokens = snapshot.context_window_tokens
        if self.provider is provider and self.model == model:
            return
        old_model = self.model
        self.provider = provider
        self.model = model
        self.context_window_tokens = context_window_tokens
        self.runner.provider = provider
        self.subagents.set_provider(provider, model)
        self.consolidator.set_provider(provider, model, context_window_tokens)
        self.dream.set_provider(provider, model)
        self._provider_signature = snapshot.signature
        logger.info("Runtime model switched for next turn: {} -> {}", old_model, model)

    def _refresh_provider_snapshot(self) -> None:
        if self._provider_snapshot_loader is None:
            return
        try:
            snapshot = self._provider_snapshot_loader()
        except Exception:
            logger.exception("Failed to refresh provider config")
            return
        if snapshot.signature == self._provider_signature:
            return
        self._apply_provider_snapshot(snapshot)

    def _register_default_tools(self) -> None:
        """Register the default set of tools."""
        if self.is_orchestrator:
            self._register_orchestrator_tools()
            return

        self._register_operational_tools()

    def _register_orchestrator_tools(self) -> None:
        """Register the orchestrator's coordination + message tool surface."""
        self.tools.register(SpawnTool(manager=self.subagents))
        self.tools.register(BlackboardReadTool(blackboard=lambda: self.blackboard))
        self.tools.register(ReadAssetsTool(feed=lambda: self.asset_feed))
        self.tools.register(RequestApprovalTool())
        self.tools.register(WritePlanTool(chat_id_getter=lambda: self._current_chat_id))
        self.tools.register(
            MessageTool(send_callback=self.bus.publish_outbound, workspace=self.workspace)
        )
        # Read-only file access restricted to .secbot/ internals
        # (tool-results, scans, etc.).  The orchestrator needs this to
        # inspect persisted sub-agent result files that exceed the inline
        # tool-result size limit.
        self.tools.register(
            ReadFileTool(
                workspace=self.workspace,
                allowed_dir=self.workspace / ".secbot",
            )
        )

    def _register_operational_tools(self) -> None:
        """Register the full operational tool surface for non-orchestrator loops."""
        allowed_dir = (
            self.workspace if (self.restrict_to_workspace or self.exec_config.sandbox) else None
        )
        extra_read = [BUILTIN_SKILLS_DIR] if BUILTIN_SKILLS_DIR.exists() else None
        self.tools.register(AskUserTool())
        self.tools.register(
            ReadFileTool(
                workspace=self.workspace,
                allowed_dir=allowed_dir,
                extra_allowed_dirs=extra_read,
            )
        )
        for cls in (WriteFileTool, EditFileTool, ListDirTool):
            self.tools.register(cls(workspace=self.workspace, allowed_dir=allowed_dir))
        for cls in (GlobTool, GrepTool):
            self.tools.register(cls(workspace=self.workspace, allowed_dir=allowed_dir))
        self.tools.register(NotebookEditTool(workspace=self.workspace, allowed_dir=allowed_dir))
        # Hard-disabled: operational (non-orchestrator) loops never register
        # ExecTool. Subagents MAY receive ExecTool only when spawned with an
        # expert-agent spec that has allow_exec=True AND exec_config.enable.
        # See subagent.py for the conditional gate.
        self.tools.register(CurlTool())
        self.tools.register(MessageTool(send_callback=self.bus.publish_outbound, workspace=self.workspace))
        self.tools.register(SpawnTool(manager=self.subagents))
        self.tools.register(BlackboardWriteTool(blackboard=lambda: self.blackboard, agent_name="orchestrator"))
        self.tools.register(BlackboardReadTool(blackboard=lambda: self.blackboard))
        # Asset feed: register both push (write) and read tools on the
        # operational loop so a chat-driven non-orchestrator agent can
        # also append discoveries without going through a sub-agent.
        self.tools.register(
            AssetPushTool(
                feed=lambda: self.asset_feed,
                bus=self.bus,
                origin=lambda: {
                    "channel": "system",
                    "chat_id": self._current_chat_id or "",
                },
                agent_name="operational",
            )
        )
        self.tools.register(ReadAssetsTool(feed=lambda: self.asset_feed))
        # Register every valid secbot skill as a first-class tool so the LLM
        # can invoke qscan / fscan / hydra / nuclei etc. with typed parameters
        # instead of synthesising shell commands via ``exec``. Skills whose
        # front-matter does not comply with the secbot SKILL.md schema are
        # silently skipped (scan_skills strict=False).
        for skill_tool in discover_skill_tools(
            BUILTIN_SKILLS_DIR,
            workspace=self.workspace,
            high_risk_gate=self._high_risk_gate,
        ):
            self.tools.register(skill_tool)
        if self.cron_service:
            self.tools.register(
                CronTool(self.cron_service, default_timezone=self.context.timezone or "UTC")
            )

    async def _connect_mcp(self) -> None:
        """Connect to configured MCP servers (one-time, lazy)."""
        if self.is_orchestrator:
            return
        if self._mcp_connected or self._mcp_connecting or not self._mcp_servers:
            return
        self._mcp_connecting = True
        from secbot.agent.tools.mcp import connect_mcp_servers

        try:
            self._mcp_stacks = await connect_mcp_servers(self._mcp_servers, self.tools)
            if self._mcp_stacks:
                self._mcp_connected = True
            else:
                logger.warning("No MCP servers connected successfully (will retry next message)")
        except asyncio.CancelledError:
            logger.warning("MCP connection cancelled (will retry next message)")
            self._mcp_stacks.clear()
        except BaseException as e:
            logger.warning("Failed to connect MCP servers (will retry next message): {}", e)
            self._mcp_stacks.clear()
        finally:
            self._mcp_connecting = False

    def _set_tool_context(
        self, channel: str, chat_id: str,
        message_id: str | None = None, metadata: dict | None = None,
        session_key: str | None = None,
    ) -> None:
        """Update context for all tools that need routing info."""
        # When the caller threads a thread-scoped session_key (e.g. slack with
        # reply_in_thread: true), honor it so spawn announces route back to
        # the originating thread session. Falls back to unified mode or
        # channel:chat_id for callers that don't have a thread-scoped key.
        if session_key is not None:
            effective_key = session_key
        elif self._unified_session:
            effective_key = UNIFIED_SESSION_KEY
        else:
            effective_key = f"{channel}:{chat_id}"
        self._current_chat_id = chat_id
        for name in ("message", "create_agent", "cron", "my"):
            if tool := self.tools.get(name):
                if hasattr(tool, "set_context"):
                    if name == "create_agent":
                        tool.set_context(channel, chat_id, effective_key=effective_key)
                        if hasattr(tool, "set_origin_message_id"):
                            tool.set_origin_message_id(message_id)
                    elif name == "cron":
                        tool.set_context(channel, chat_id, metadata=metadata, session_key=session_key)
                    elif name == "message":
                        tool.set_context(channel, chat_id, message_id, metadata=metadata)
                    else:
                        tool.set_context(channel, chat_id)

    @staticmethod
    def _strip_think(text: str | None) -> str | None:
        """Remove <think>…</think> blocks that some models embed in content."""
        if not text:
            return None
        from secbot.utils.helpers import strip_think

        return strip_think(text) or None

    @staticmethod
    def _runtime_chat_id(msg: InboundMessage) -> str:
        """Return the chat id shown in runtime metadata for the model."""
        return str(msg.metadata.get("context_chat_id") or msg.chat_id)

    def _tool_hint(self, tool_calls: list) -> str:
        """Format tool calls as concise hints with smart abbreviation."""
        from secbot.utils.tool_hints import format_tool_hints

        return format_tool_hints(tool_calls, max_length=self.tool_hint_max_length)

    async def _dispatch_command_inline(
        self,
        msg: InboundMessage,
        key: str,
        raw: str,
        dispatch_fn: Callable[[CommandContext], Awaitable[OutboundMessage | None]],
    ) -> None:
        """Dispatch a command directly from the run() loop and publish the result."""
        # Priority / inline commands (e.g. ``/stop``) must see the live session
        # so they can inspect or patch its message tail. Without this, a
        # ``/stop`` issued while the agent is mid tool-call would leave a
        # trailing ``assistant`` message with ``tool_calls`` but no matching
        # ``tool`` result on disk — the WebUI then reads that as "still
        # working" every time the user reopens the chat, so the Stop button
        # never goes away. ``get_or_create`` is safe: if the session really
        # does not exist yet, the cancel-cleanup branches become no-ops.
        try:
            session = self.sessions.get_or_create(key)
        except Exception:
            session = None
        ctx = CommandContext(msg=msg, session=session, key=key, raw=raw, loop=self)
        result = await dispatch_fn(ctx)
        if result:
            await self.bus.publish_outbound(result)
        else:
            logger.warning("Command '{}' matched but dispatch returned None", raw)

    async def _cancel_active_tasks(self, key: str) -> int:
        """Cancel and await all active tasks and subagents for *key*.

        Returns the total number of cancelled tasks + subagents.
        """
        tasks = self._active_tasks.pop(key, [])
        cancelled = sum(1 for t in tasks if not t.done() and t.cancel())
        for t in tasks:
            with suppress(asyncio.CancelledError, Exception):
                await t
        sub_cancelled = await self.subagents.cancel_by_session(key)
        return cancelled + sub_cancelled

    def _effective_session_key(self, msg: InboundMessage) -> str:
        """Return the session key used for task routing and mid-turn injections."""
        if self._unified_session and not msg.session_key_override:
            return UNIFIED_SESSION_KEY
        return msg.session_key

    def _replay_token_budget(self) -> int:
        """Derive a token budget for session history replay from the context window."""
        if self.context_window_tokens <= 0:
            return 0
        max_output = getattr(getattr(self.provider, "generation", None), "max_tokens", 4096)
        try:
            reserved_output = int(max_output)
        except (TypeError, ValueError):
            reserved_output = 4096
        budget = self.context_window_tokens - max(1, reserved_output) - 1024
        return budget if budget > 0 else max(128, self.context_window_tokens // 2)

    async def _run_agent_loop(
        self,
        initial_messages: list[dict],
        on_progress: Callable[..., Awaitable[None]] | None = None,
        on_stream: Callable[[str], Awaitable[None]] | None = None,
        on_stream_end: Callable[..., Awaitable[None]] | None = None,
        on_retry_wait: Callable[[str], Awaitable[None]] | None = None,
        *,
        session: Session | None = None,
        channel: str = "cli",
        chat_id: str = "direct",
        message_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        session_key: str | None = None,
        pending_queue: asyncio.Queue | None = None,
    ) -> tuple[str | None, list[str], list[dict], str, bool]:
        """Run the agent iteration loop.

        *on_stream*: called with each content delta during streaming.
        *on_stream_end(resuming)*: called when a streaming session finishes.
        ``resuming=True`` means tool calls follow (spinner should restart);
        ``resuming=False`` means this is the final response.

        Returns (final_content, tools_used, messages, stop_reason, had_injections).
        """
        self._sync_subagent_runtime_limits()

        loop_hook = _LoopHook(
            self,
            on_progress=on_progress,
            on_stream=on_stream,
            on_stream_end=on_stream_end,
            channel=channel,
            chat_id=chat_id,
            message_id=message_id,
            metadata=metadata,
            session_key=session_key,
        )
        hook: AgentHook = (
            CompositeHook([loop_hook] + self._extra_hooks) if self._extra_hooks else loop_hook
        )

        async def _checkpoint(payload: dict[str, Any]) -> None:
            if session is None:
                return
            self._set_runtime_checkpoint(session, payload)

        async def _drain_pending(*, limit: int = _MAX_INJECTIONS_PER_TURN) -> list[dict[str, Any]]:
            """Drain follow-up messages from the pending queue.

            When no messages are immediately available but sub-agents
            spawned in this dispatch are still running, blocks until at
            least one result arrives (or timeout).  This keeps the runner
            loop alive so subsequent sub-agent completions are consumed
            in-order rather than dispatched separately.
            """
            if pending_queue is None:
                return []

            def _to_user_message(pending_msg: InboundMessage) -> dict[str, Any]:
                content = pending_msg.content
                media = pending_msg.media if pending_msg.media else None
                if media:
                    content, media = extract_documents(content, media)
                    media = media or None
                user_content = self.context._build_user_content(content, media)
                runtime_ctx = self.context._build_runtime_context(
                    pending_msg.channel,
                    self._runtime_chat_id(pending_msg),
                    self.context.timezone,
                )
                if isinstance(user_content, str):
                    merged: str | list[dict[str, Any]] = f"{runtime_ctx}\n\n{user_content}"
                else:
                    merged = [{"type": "text", "text": runtime_ctx}] + user_content
                message: dict[str, Any] = {"role": "user", "content": merged}
                if isinstance(pending_msg.metadata, dict):
                    injected_event = pending_msg.metadata.get("injected_event")
                    if isinstance(injected_event, str) and injected_event:
                        message["injected_event"] = injected_event
                        task_id = pending_msg.metadata.get("subagent_task_id")
                        if task_id is not None:
                            message["subagent_task_id"] = str(task_id)
                        if pending_msg.sender_id:
                            message["sender_id"] = str(pending_msg.sender_id)
                return message

            def _event_name(pending_msg: InboundMessage) -> str | None:
                metadata = pending_msg.metadata if isinstance(pending_msg.metadata, dict) else {}
                event = metadata.get("injected_event")
                return event if isinstance(event, str) and event else None

            def _priority(pending_msg: InboundMessage) -> int:
                event = _event_name(pending_msg)
                if event is None and pending_msg.channel != "system":
                    return 0
                if event == "subagent_result":
                    return 1
                if event == "asset_discovered":
                    return 3
                return 2

            def _drain_available() -> list[InboundMessage]:
                drained: list[InboundMessage] = []
                while True:
                    try:
                        drained.append(pending_queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break
                return drained

            def _select_pending(batch: list[InboundMessage]) -> list[InboundMessage]:
                if not batch:
                    return []

                completed_agents = {
                    msg.sender_id
                    for msg in batch
                    if _event_name(msg) == "subagent_result" and msg.sender_id
                }
                if completed_agents:
                    before = len(batch)
                    batch = [
                        msg for msg in batch
                        if not (
                            _event_name(msg) == "asset_discovered"
                            and msg.sender_id in completed_agents
                        )
                    ]
                    dropped = before - len(batch)
                    if dropped:
                        logger.debug(
                            "Dropped {} stale asset_discovered injection(s) after subagent_result",
                            dropped,
                        )

                ordered = [
                    msg for _, msg in sorted(
                        enumerate(batch),
                        key=lambda pair: (_priority(pair[1]), pair[0]),
                    )
                ]
                selected = ordered[:limit]
                for leftover in ordered[limit:]:
                    pending_queue.put_nowait(leftover)
                return selected

            raw_items = _drain_available()

            # When sub-agents are running, ``asset_discovered`` wake-up
            # notifications are noise – they consume injection cycles that
            # should be reserved for the actual ``subagent_result``.  Discard
            # them while sub-agents are active and keep waiting for the real
            # completion signal.
            def _discard_asset_notifications(
                items: list[InboundMessage],
            ) -> list[InboundMessage]:
                """Drop asset_discovered messages when sub-agents are active."""
                if session is None:
                    return items
                if self.subagents.get_running_count_by_session(session.key) <= 0:
                    return items
                kept = [m for m in items if _event_name(m) != "asset_discovered"]
                dropped = len(items) - len(kept)
                if dropped:
                    logger.info(
                        "Dropped {} asset_discovered notification(s) while "
                        "sub-agent(s) running",
                        dropped,
                    )
                return kept

            raw_items = _discard_asset_notifications(raw_items)

            # Block if nothing drained but sub-agents spawned in this dispatch
            # are still running. Keeps the runner loop alive so subsequent
            # completions are injected promptly. Once a completion is present,
            # it is prioritised over stale per-asset wake-ups from that same
            # completed sub-agent.
            if (not raw_items
                    and session is not None
                    and self.subagents.get_running_count_by_session(session.key) > 0):
                try:
                    while True:
                        item = await asyncio.wait_for(
                            pending_queue.get(), timeout=300,
                        )
                        if _event_name(item) == "asset_discovered":
                            logger.debug(
                                "Discarded asset_discovered notification "
                                "while waiting for sub-agent completion",
                            )
                            continue
                        raw_items.append(item)
                        break
                except asyncio.TimeoutError:
                    logger.warning(
                        "Timeout waiting for sub-agent completion in session {}",
                        session.key,
                    )
                    return []
                # Drain additional items and discard asset notifications
                extra = _discard_asset_notifications(_drain_available())
                raw_items.extend(extra)

            return [_to_user_message(item) for item in _select_pending(raw_items)]

        active_session_key = session.key if session else session_key
        file_state_token = bind_file_states(self._file_state_store.for_session(active_session_key))

        # Bind SkillContext for this turn so every SkillTool.execute sees a
        # stable scan_id + scan_dir. Raw logs land under ``<workspace>/.secbot
        # /scans/<session>/raw`` (directory is created lazily by SkillContext).
        scan_id = (active_session_key or "adhoc").replace(":", "_") or "adhoc"
        scan_dir = self.workspace / ".secbot" / "scans" / scan_id
        scan_dir.mkdir(parents=True, exist_ok=True)

        # When the turn originates from the WebSocket channel, wire up the
        # ``ctx.confirm`` callback so critical-risk skills can surface a
        # blocking dialog to the WebUI via ``surface_confirm``. Non-WS
        # channels (CLI/API) leave confirm=None which causes HighRiskGate to
        # run skills unconditionally (no UI to ask).
        confirm_fn = None
        if channel == "websocket":
            from secbot.channels.websocket import WebSocketChannel

            _ws = WebSocketChannel.get_active_instance()
            if _ws is not None:
                _chat = chat_id  # capture for closure

                async def confirm_fn(payload):  # type: ignore[assignment]
                    return await _ws.surface_confirm(payload, chat_id=_chat)

        asset_auto_management_enabled = False
        if active_session_key and self.sessions is not None:
            with suppress(Exception):
                asset_auto_management_enabled = (
                    self.sessions.get_asset_auto_management(active_session_key)
                )

        bind_skill_context(
            scan_id=scan_id,
            scan_dir=scan_dir,
            confirm=confirm_fn,
            asset_auto_management_enabled=asset_auto_management_enabled,
        )

        # Resolve / install the chat-scoped blackboard (PRD D3). Every
        # ``self.blackboard`` reference (orchestrator tools, the Subagent
        # tools registered via callable, broadcast bind below) follows the
        # same pointer so a single chat keeps a single board across turns
        # and across spawned subagents.
        active_blackboard = await self.blackboard_registry.get_or_create(chat_id)
        self.blackboard = active_blackboard

        # PR-1: rebind the active asset feed for the current chat. The
        # registered AssetPushTool / ReadAssetsTool resolve via a
        # callable that returns ``self.asset_feed``, so this single
        # assignment redirects every subsequent tool invocation in this
        # turn (and any sub-agents spawned from it) to the right feed.
        self.asset_feed = await self.asset_feed_registry.get_or_create(chat_id)

        # Bind blackboard write callback for websocket channels so entries
        # are broadcast to the chat surface in real-time.
        if channel == "websocket":
            from secbot.channels.websocket import WebSocketChannel

            ws_channel = WebSocketChannel.get_active_instance()
            if ws_channel is not None:
                def _on_bb_write(entry) -> None:
                    asyncio.create_task(
                        ws_channel.broadcast_agent_event(
                            chat_id=chat_id,
                            type="blackboard_entry",
                            payload=entry.to_dict(),
                        )
                    )
                active_blackboard.set_on_write(_on_bb_write)

                def _on_asset_push(entry) -> None:
                    asyncio.create_task(
                        ws_channel.broadcast_agent_event(
                            chat_id=chat_id,
                            type="asset_pushed",
                            payload=entry.to_dict(),
                        )
                    )
                self.asset_feed.set_on_append(_on_asset_push)
            else:
                active_blackboard.set_on_write(None)
                self.asset_feed.set_on_append(None)
        else:
            active_blackboard.set_on_write(None)
            self.asset_feed.set_on_append(None)

        try:
            result = await self.runner.run(AgentRunSpec(
                initial_messages=initial_messages,
                tools=self.tools,
                model=self.model,
                max_iterations=self.max_iterations,
                max_tool_result_chars=self.max_tool_result_chars,
                hook=hook,
                error_message="Sorry, I encountered an error calling the AI model.",
                concurrent_tools=True,
                workspace=self.workspace,
                session_key=session.key if session else None,
                context_window_tokens=self.context_window_tokens,
                context_block_limit=self.context_block_limit,
                provider_retry_mode=self.provider_retry_mode,
                progress_callback=on_progress,
                stream_progress_deltas=on_stream is not None,
                retry_wait_callback=on_retry_wait,
                checkpoint_callback=_checkpoint,
                injection_callback=_drain_pending,
            ))
        finally:
            reset_file_states(file_state_token)
            active_blackboard.set_on_write(None)
        self._last_usage = result.usage
        if result.stop_reason == "max_iterations":
            logger.warning("Max iterations ({}) reached", self.max_iterations)
            # Push final content through stream so streaming channels (e.g. Feishu)
            # update the card instead of leaving it empty.
            if on_stream and on_stream_end:
                await on_stream(result.final_content or "")
                await on_stream_end(resuming=False)
        elif result.stop_reason == "error":
            logger.error("LLM returned error: {}", (result.final_content or "")[:200])
        return result.final_content, result.tools_used, result.messages, result.stop_reason, result.had_injections

    async def run(self) -> None:
        """Run the agent loop, dispatching messages as tasks to stay responsive to /stop."""
        self._running = True
        await self._connect_mcp()
        logger.info("Agent loop started")

        while self._running:
            try:
                msg = await asyncio.wait_for(self.bus.consume_inbound(), timeout=1.0)
            except asyncio.TimeoutError:
                self.auto_compact.check_expired(
                    self._schedule_background,
                    active_session_keys=self._pending_queues.keys(),
                )
                continue
            except asyncio.CancelledError:
                # Preserve real task cancellation so shutdown can complete cleanly.
                # Only ignore non-task CancelledError signals that may leak from integrations.
                if not self._running or asyncio.current_task().cancelling():
                    raise
                continue
            except Exception as e:
                logger.warning("Error consuming inbound message: {}, continuing...", e)
                continue

            raw = msg.content.strip()
            if self.commands.is_priority(raw):
                await self._dispatch_command_inline(
                    msg, msg.session_key, raw,
                    self.commands.dispatch_priority,
                )
                continue
            effective_key = self._effective_session_key(msg)
            # If this session already has an active pending queue (i.e. a task
            # is processing this session), route the message there for mid-turn
            # injection instead of creating a competing task.
            if effective_key in self._pending_queues:
                # Non-priority commands must not be queued for injection;
                # dispatch them directly (same pattern as priority commands).
                if self.commands.is_dispatchable_command(raw):
                    await self._dispatch_command_inline(
                        msg, effective_key, raw,
                        self.commands.dispatch,
                    )
                    continue
                pending_msg = msg
                if effective_key != msg.session_key:
                    pending_msg = dataclasses.replace(
                        msg,
                        session_key_override=effective_key,
                    )
                try:
                    self._pending_queues[effective_key].put_nowait(pending_msg)
                except asyncio.QueueFull:
                    logger.warning(
                        "Pending queue full for session {}, re-publishing to bus",
                        effective_key,
                    )
                    await self.bus.publish_inbound(pending_msg)
                else:
                    logger.info(
                        "Routed follow-up message to pending queue for session {}",
                        effective_key,
                    )
                    continue
            # Compute the effective session key before dispatching
            # This ensures /stop command can find tasks correctly when unified session is enabled
            task = asyncio.create_task(self._dispatch(msg))
            self._active_tasks.setdefault(effective_key, []).append(task)
            task.add_done_callback(
                lambda t, k=effective_key: self._active_tasks.get(k, [])
                and self._active_tasks[k].remove(t)
                if t in self._active_tasks.get(k, [])
                else None
            )

    async def _dispatch(self, msg: InboundMessage) -> None:
        """Process a message: per-session serial, cross-session concurrent."""
        session_key = self._effective_session_key(msg)
        if session_key != msg.session_key:
            msg = dataclasses.replace(msg, session_key_override=session_key)
        lock = self._session_locks.setdefault(session_key, asyncio.Lock())
        gate = self._concurrency_gate or nullcontext()

        # Register a pending queue so follow-up messages for this session are
        # routed here (mid-turn injection) instead of spawning a new task.
        pending = asyncio.Queue(maxsize=20)
        self._pending_queues[session_key] = pending

        try:
            async with lock, gate:
                try:
                    on_stream = on_stream_end = None
                    if msg.metadata.get("_wants_stream"):
                        # Split one answer into distinct stream segments.
                        stream_base_id = f"{msg.session_key}:{time.time_ns()}"
                        stream_segment = 0

                        def _current_stream_id() -> str:
                            return f"{stream_base_id}:{stream_segment}"

                        async def on_stream(delta: str) -> None:
                            meta = dict(msg.metadata or {})
                            meta["_stream_delta"] = True
                            meta["_stream_id"] = _current_stream_id()
                            await self.bus.publish_outbound(OutboundMessage(
                                channel=msg.channel, chat_id=msg.chat_id,
                                content=delta,
                                metadata=meta,
                            ))

                        async def on_stream_end(*, resuming: bool = False) -> None:
                            nonlocal stream_segment
                            meta = dict(msg.metadata or {})
                            meta["_stream_end"] = True
                            meta["_resuming"] = resuming
                            meta["_stream_id"] = _current_stream_id()
                            await self.bus.publish_outbound(OutboundMessage(
                                channel=msg.channel, chat_id=msg.chat_id,
                                content="",
                                metadata=meta,
                            ))
                            stream_segment += 1

                    response = await self._process_message(
                        msg, on_stream=on_stream, on_stream_end=on_stream_end,
                        pending_queue=pending,
                    )
                    if response is not None:
                        await self.bus.publish_outbound(response)
                    elif msg.channel == "cli":
                        await self.bus.publish_outbound(OutboundMessage(
                            channel=msg.channel, chat_id=msg.chat_id,
                            content="", metadata=msg.metadata or {},
                        ))
                    if msg.channel == "websocket":
                        # Signal that the turn is fully complete (all tools executed,
                        # final text streamed).  This lets WS clients know when to
                        # definitively stop the loading indicator.
                        turn_meta = {**msg.metadata, "_turn_end": True}
                        if self._last_usage:
                            turn_meta["_usage"] = self._last_usage
                        await self.bus.publish_outbound(OutboundMessage(
                            channel=msg.channel, chat_id=msg.chat_id,
                            content="", metadata=turn_meta,
                        ))
                        if msg.metadata.get("webui") is True:
                            async def _generate_title_and_notify() -> None:
                                generated = await maybe_generate_webui_title_after_turn(
                                    channel=msg.channel,
                                    metadata=msg.metadata,
                                    sessions=self.sessions,
                                    session_key=session_key,
                                    provider=self.provider,
                                    model=self.model,
                                )
                                if generated:
                                    await self.bus.publish_outbound(OutboundMessage(
                                        channel=msg.channel,
                                        chat_id=msg.chat_id,
                                        content="",
                                        metadata={**msg.metadata, "_session_updated": True},
                                    ))

                            self._schedule_background(_generate_title_and_notify())
                except asyncio.CancelledError:
                    logger.info("Task cancelled for session {}", session_key)
                    # Preserve partial context from the interrupted turn so
                    # the user does not lose tool results and assistant
                    # messages accumulated before /stop.  The checkpoint was
                    # already persisted to session metadata by
                    # _emit_checkpoint during tool execution; materializing
                    # it into session history now makes it visible in the
                    # next conversation turn.
                    try:
                        key = self._effective_session_key(msg)
                        session = self.sessions.get_or_create(key)
                        if self._restore_runtime_checkpoint(session):
                            self._clear_pending_user_turn(session)
                            self.sessions.save(session)
                            logger.info(
                                "Restored partial context for cancelled session {}",
                                key,
                            )
                    except Exception:
                        logger.debug(
                            "Could not restore checkpoint for cancelled session {}",
                            session_key,
                            exc_info=True,
                        )
                    raise
                except Exception:
                    logger.exception("Error processing message for session {}", session_key)
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=msg.channel, chat_id=msg.chat_id,
                        content="Sorry, I encountered an error.",
                    ))
        finally:
            # Drain any messages still in the pending queue and re-publish
            # them to the bus so they are processed as fresh inbound messages
            # rather than silently lost.
            queue = self._pending_queues.pop(session_key, None)
            if queue is not None:
                leftover = 0
                while True:
                    try:
                        item = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    await self.bus.publish_inbound(item)
                    leftover += 1
                if leftover:
                    logger.info(
                        "Re-published {} leftover message(s) to bus for session {}",
                        leftover, session_key,
                    )

    async def close_mcp(self) -> None:
        """Drain pending background archives, then close MCP connections."""
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
            self._background_tasks.clear()
        for name, stack in self._mcp_stacks.items():
            try:
                await stack.aclose()
            except (RuntimeError, BaseExceptionGroup):
                logger.debug("MCP server '{}' cleanup error (can be ignored)", name)
        self._mcp_stacks.clear()

    def _schedule_background(self, coro) -> None:
        """Schedule a coroutine as a tracked background task (drained on shutdown)."""
        task = asyncio.create_task(coro)
        self._background_tasks.append(task)
        task.add_done_callback(self._background_tasks.remove)

    def stop(self) -> None:
        """Stop the agent loop."""
        self._running = False
        logger.info("Agent loop stopping")

    async def _process_message(
        self,
        msg: InboundMessage,
        session_key: str | None = None,
        on_progress: Callable[..., Awaitable[None]] | None = None,
        on_stream: Callable[[str], Awaitable[None]] | None = None,
        on_stream_end: Callable[..., Awaitable[None]] | None = None,
        pending_queue: asyncio.Queue | None = None,
    ) -> OutboundMessage | None:
        """Process a single inbound message and return the response."""
        self._refresh_provider_snapshot()
        # System messages: parse origin from chat_id ("channel:chat_id")
        if msg.channel == "system":
            channel, chat_id = (
                msg.chat_id.split(":", 1) if ":" in msg.chat_id else ("cli", msg.chat_id)
            )
            logger.info("Processing system message from {}", msg.sender_id)
            # Honor session_key_override so subagent announces from threaded
            # callers route to the originating thread session, not the
            # channel-level session derived from chat_id.
            key = msg.session_key_override or f"{channel}:{chat_id}"
            session = self.sessions.get_or_create(key)
            if self._restore_runtime_checkpoint(session):
                self.sessions.save(session)
            if self._restore_pending_user_turn(session):
                self.sessions.save(session)

            session, pending = self.auto_compact.prepare_session(session, key)
            if pending:
                logger.info("Memory compact triggered for session {}", key)

            await self.consolidator.maybe_consolidate_by_tokens(
                session,
                session_summary=pending,
            )
            # Persist subagent follow-ups into durable history BEFORE prompt
            # assembly. ContextBuilder merges adjacent same-role messages for
            # provider compatibility, which previously caused the follow-up to
            # disappear from session.messages while still being visible to the
            # LLM via the merged prompt. See _persist_subagent_followup.
            is_subagent = msg.sender_id == "subagent" or (
                isinstance(msg.metadata, dict)
                and msg.metadata.get("injected_event") == "subagent_result"
            )
            if is_subagent and self._persist_subagent_followup(session, msg):
                logger.debug("Subagent result persisted for session {}", key)
                self.sessions.save(session)
            self._set_tool_context(
                channel, chat_id, msg.metadata.get("message_id"),
                msg.metadata, session_key=key,
            )
            _hist_kwargs: dict[str, Any] = {
                "max_messages": self._max_messages,
                "max_tokens": self._replay_token_budget(),
                "include_timestamps": True,
            }
            history = session.get_history(**_hist_kwargs)
            current_role = "assistant" if is_subagent else "user"

            # Subagent content is already in `history` above; passing it again
            # as current_message would double-project it into the prompt.
            messages = self.context.build_messages(
                history=history,
                current_message="" if is_subagent else msg.content,
                channel=channel,
                chat_id=chat_id,
                session_summary=pending,
                current_role=current_role,
                sender_id=msg.sender_id,
                is_orchestrator=self.is_orchestrator,
                agent_registry=self._agent_registry,
            )
            final_content, _, all_msgs, stop_reason, _ = await self._run_agent_loop(
                messages, session=session, channel=channel, chat_id=chat_id,
                message_id=msg.metadata.get("message_id"),
                metadata=msg.metadata,
                session_key=key,
                pending_queue=pending_queue,
            )
            # Auto-continue when the main agent hits iteration/context limits:
            # inject the interrupt summary as a continuation prompt and start a
            # fresh loop (iteration counter resets, context window is clean).
            _MAX_CONTINUATIONS = 5
            _continuations = 0
            while stop_reason in ("max_iterations", "context_exhausted") and _continuations < _MAX_CONTINUATIONS:
                _continuations += 1
                _summary = final_content or f"[会话中断 — {stop_reason}]"
                logger.info(
                    "Auto-continue #{}: {} — restarting agent loop with summary",
                    _continuations, stop_reason,
                )
                _cont_msgs = self.context.build_messages(
                    history="",
                    current_message=(
                        f"[会话中断续接 #{_continuations}]\n\n"
                        f"上一次执行因{('轮次耗尽' if stop_reason == 'max_iterations' else '上下文窗口已满')}而中断。"
                        f"以下是中断时的进度摘要，请从断点处继续完成任务：\n\n{_summary}"
                    ),
                    channel=channel,
                    chat_id=chat_id,
                    is_orchestrator=self.is_orchestrator,
                    agent_registry=self._agent_registry,
                )
                final_content, _, _cont_msgs, stop_reason, _ = await self._run_agent_loop(
                    _cont_msgs, session=session, channel=channel, chat_id=chat_id,
                    message_id=msg.metadata.get("message_id"),
                    metadata=msg.metadata,
                    session_key=key,
                    pending_queue=pending_queue,
                )
                all_msgs.extend(_cont_msgs)
            if stop_reason in ("max_iterations", "context_exhausted"):
                logger.warning(
                    "Auto-continue exhausted after {} rounds; reporting final state",
                    _MAX_CONTINUATIONS,
                )
            self._save_turn(session, all_msgs, 1 + len(history))
            session.enforce_file_cap(on_archive=self.context.memory.raw_archive)
            self._clear_runtime_checkpoint(session)
            self._persist_turn_usage(session)
            self.sessions.save(session)
            self._schedule_background(self.consolidator.maybe_consolidate_by_tokens(session))
            options = ask_user_options_from_messages(all_msgs) if stop_reason == "ask_user" else []
            content, buttons = ask_user_outbound(
                final_content or "Background task completed.",
                options,
                channel,
            )
            # Reconstruct channel-specific metadata from session.key so the
            # outbound reply lands in the originating thread (not the channel
            # top-level). The announce InboundMessage carries only
            # injected_event metadata; we recover thread_ts from the session
            # key, which slack writes as "slack:<chat_id>:<thread_ts>".
            outbound_metadata: dict[str, Any] = {}
            if stop_reason == "ask_user":
                if pending_prompt := pending_ask_user_call(all_msgs):
                    outbound_metadata["_prompt_tool_name"] = pending_prompt[1]
            if channel == "slack" and key.startswith("slack:") and key.count(":") >= 2:
                outbound_metadata["slack"] = {"thread_ts": key.split(":", 2)[2]}
            if origin_message_id := msg.metadata.get("origin_message_id"):
                outbound_metadata["origin_message_id"] = origin_message_id
            return OutboundMessage(
                channel=channel,
                chat_id=chat_id,
                content=content,
                buttons=buttons,
                metadata=outbound_metadata,
            )

        # Extract document text from media at the processing boundary so all
        # channels benefit without format-specific logic in ContextBuilder.
        if msg.media:
            new_content, image_only = extract_documents(msg.content, msg.media)
            msg = dataclasses.replace(msg, content=new_content, media=image_only)

        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        logger.info("Processing message from {}:{}: {}", msg.channel, msg.sender_id, preview)

        key = session_key or msg.session_key
        session = self.sessions.get_or_create(key)
        mark_webui_session(session, msg.metadata)
        if self._restore_runtime_checkpoint(session):
            self.sessions.save(session)
        if self._restore_pending_user_turn(session):
            self.sessions.save(session)

        session, pending = self.auto_compact.prepare_session(session, key)

        # Slash commands
        raw = msg.content.strip()
        ctx = CommandContext(msg=msg, session=session, key=key, raw=raw, loop=self)
        if result := await self.commands.dispatch(ctx):
            return result

        await self.consolidator.maybe_consolidate_by_tokens(
            session,
            session_summary=pending,
        )

        self._set_tool_context(
            msg.channel, msg.chat_id, msg.metadata.get("message_id"),
            msg.metadata, session_key=key,
        )
        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool):
                message_tool.start_turn()

        _hist_kwargs: dict[str, Any] = {
            "max_messages": self._max_messages,
            "max_tokens": self._replay_token_budget(),
            "include_timestamps": True,
        }
        history = session.get_history(**_hist_kwargs)

        pending_ask = pending_ask_user_call(history)
        pending_ask_id = pending_ask[0] if pending_ask else None
        if pending_ask:
            pending_ask_id, pending_ask_tool = pending_ask
            initial_messages = ask_user_tool_result_messages(
                self.context.build_system_prompt(
                    channel=msg.channel,
                    is_orchestrator=self.is_orchestrator,
                    agent_registry=self._agent_registry,
                ),
                history,
                pending_ask_id,
                msg.content,
                tool_name=pending_ask_tool,
            )
        else:
            initial_messages = self.context.build_messages(
                history=history,
                current_message=msg.content,
                session_summary=pending,
                media=msg.media if msg.media else None,
                channel=msg.channel,
                chat_id=self._runtime_chat_id(msg),
                sender_id=msg.sender_id,
                is_orchestrator=self.is_orchestrator,
                agent_registry=self._agent_registry,
            )

        async def _bus_progress(
            content: str,
            *,
            tool_hint: bool = False,
            tool_events: list[dict[str, Any]] | None = None,
        ) -> None:
            meta = dict(msg.metadata or {})
            meta["_progress"] = True
            meta["_tool_hint"] = tool_hint
            if tool_events:
                meta["_tool_events"] = tool_events
            await self.bus.publish_outbound(
                OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=content,
                    metadata=meta,
                )
            )

        async def _on_retry_wait(content: str) -> None:
            meta = dict(msg.metadata or {})
            meta["_retry_wait"] = True
            await self.bus.publish_outbound(
                OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=content,
                    metadata=meta,
                )
            )

        # Persist the triggering user message up front so a mid-turn crash
        # doesn't silently lose the prompt on recovery. ``media`` rides along
        # as raw on-disk paths — sanitized image blocks are stripped from
        # JSONL, and webui replay needs the paths to mint signed URLs.
        # ``injected_event`` / ``sender_id`` are preserved so the frontend
        # can filter internal notifications (e.g. asset_discovered) from
        # the user-visible chat replay.
        user_persisted_early = False
        media_paths = [p for p in (msg.media or []) if isinstance(p, str) and p]
        has_text = isinstance(msg.content, str) and msg.content.strip()
        if not pending_ask_id and (has_text or media_paths):
            extra: dict[str, Any] = {"media": list(media_paths)} if media_paths else {}
            text = msg.content if isinstance(msg.content, str) else ""
            # Carry injected_event + sender_id so frontend filters work.
            if isinstance(msg.metadata, dict):
                _ie = msg.metadata.get("injected_event")
                if isinstance(_ie, str) and _ie:
                    extra["injected_event"] = _ie
                _sid = msg.metadata.get("sender_id") or msg.sender_id
                if isinstance(_sid, str) and _sid:
                    extra["sender_id"] = _sid
            session.add_message("user", text, **extra)
            self._mark_pending_user_turn(session)
            self.sessions.save(session)
            user_persisted_early = True

        final_content, _, all_msgs, stop_reason, had_injections = await self._run_agent_loop(
            initial_messages,
            on_progress=on_progress or _bus_progress,
            on_stream=on_stream,
            on_stream_end=on_stream_end,
            on_retry_wait=_on_retry_wait,
            session=session,
            channel=msg.channel,
            chat_id=msg.chat_id,
            message_id=msg.metadata.get("message_id"),
            metadata=msg.metadata,
            session_key=key,
            pending_queue=pending_queue,
        )

        # Auto-continue when the main agent hits iteration/context limits:
        # inject the interrupt summary as a continuation prompt and start a
        # fresh loop (iteration counter resets, context window is clean).
        _MAX_CONTINUATIONS = 5
        _continuations = 0
        while stop_reason in ("max_iterations", "context_exhausted") and _continuations < _MAX_CONTINUATIONS:
            _continuations += 1
            _summary = final_content or f"[会话中断 — {stop_reason}]"
            logger.info(
                "Auto-continue #{}: {} — restarting agent loop with summary",
                _continuations, stop_reason,
            )
            _cont_msgs = self.context.build_messages(
                history="",
                current_message=(
                    f"[会话中断续接 #{_continuations}]\n\n"
                    f"上一次执行因{('轮次耗尽' if stop_reason == 'max_iterations' else '上下文窗口已满')}而中断。"
                    f"以下是中断时的进度摘要，请从断点处继续完成任务：\n\n{_summary}"
                ),
                channel=msg.channel,
                chat_id=msg.chat_id,
                is_orchestrator=self.is_orchestrator,
                agent_registry=self._agent_registry,
            )
            _fc, _, _cm, stop_reason, _hi = await self._run_agent_loop(
                _cont_msgs,
                on_progress=on_progress or _bus_progress,
                on_stream=on_stream,
                on_stream_end=on_stream_end,
                on_retry_wait=_on_retry_wait,
                session=session,
                channel=msg.channel,
                chat_id=msg.chat_id,
                message_id=msg.metadata.get("message_id"),
                metadata=msg.metadata,
                session_key=key,
                pending_queue=pending_queue,
            )
            final_content = _fc or final_content
            all_msgs.extend(_cm)
            if _hi:
                had_injections = True
        if stop_reason in ("max_iterations", "context_exhausted"):
            logger.warning(
                "Auto-continue exhausted after {} rounds; reporting final state",
                _MAX_CONTINUATIONS,
            )

        if final_content is None or not final_content.strip():
            final_content = EMPTY_FINAL_RESPONSE_MESSAGE

        # Skip the already-persisted user message when saving the turn
        save_skip = 1 + len(history) + (1 if user_persisted_early else 0)
        self._save_turn(session, all_msgs, save_skip)
        session.enforce_file_cap(on_archive=self.context.memory.raw_archive)
        self._clear_pending_user_turn(session)
        self._clear_runtime_checkpoint(session)
        self._persist_turn_usage(session)
        self.sessions.save(session)
        self._schedule_background(self.consolidator.maybe_consolidate_by_tokens(session))

        # When follow-up messages were injected mid-turn, a later natural
        # language reply may address those follow-ups and should not be
        # suppressed just because MessageTool was used earlier in the turn.
        # However, if the turn falls back to the empty-final-response
        # placeholder, suppress it when the real user-visible output already
        # came from MessageTool.
        if (mt := self.tools.get("message")) and isinstance(mt, MessageTool) and mt._sent_in_turn:
            if not had_injections or stop_reason == "empty_final_response":
                return None

        preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
        logger.info("Response to {}:{}: {}", msg.channel, msg.sender_id, preview)

        meta = dict(msg.metadata or {})
        if stop_reason == "ask_user":
            if pending_prompt := pending_ask_user_call(all_msgs):
                meta["_prompt_tool_name"] = pending_prompt[1]
        final_content, buttons = ask_user_outbound(
            final_content,
            ask_user_options_from_messages(all_msgs) if stop_reason == "ask_user" else [],
            msg.channel,
        )
        if on_stream is not None and stop_reason not in {"ask_user", "error", "tool_error"}:
            meta["_streamed"] = True

        # Auto-attach report files so the WebUI can render them as clickable
        # download cards instead of plain-text paths.
        report_media = _extract_report_media(all_msgs, final_content)
        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=final_content,
            media=report_media,
            metadata=meta,
            buttons=buttons,
        )

    def _sanitize_persisted_blocks(
        self,
        content: list[dict[str, Any]],
        *,
        should_truncate_text: bool = False,
        drop_runtime: bool = False,
    ) -> list[dict[str, Any]]:
        """Strip volatile multimodal payloads before writing session history."""
        filtered: list[dict[str, Any]] = []
        for block in content:
            if not isinstance(block, dict):
                filtered.append(block)
                continue

            if (
                drop_runtime
                and block.get("type") == "text"
                and isinstance(block.get("text"), str)
                and block["text"].startswith(ContextBuilder._RUNTIME_CONTEXT_TAG)
            ):
                continue

            if block.get("type") == "image_url" and block.get("image_url", {}).get(
                "url", ""
            ).startswith("data:image/"):
                path = (block.get("_meta") or {}).get("path", "")
                filtered.append({"type": "text", "text": image_placeholder_text(path)})
                continue

            if block.get("type") == "text" and isinstance(block.get("text"), str):
                text = block["text"]
                if should_truncate_text and len(text) > self.max_tool_result_chars:
                    text = truncate_text_fn(text, self.max_tool_result_chars)
                filtered.append({**block, "text": text})
                continue

            filtered.append(block)

        return filtered

    @staticmethod
    def _strip_runtime_context_from_content(content: str) -> str | None:
        if not content.startswith(ContextBuilder._RUNTIME_CONTEXT_TAG):
            return content
        # Strip the entire runtime-context block (including any session summary).
        # The block is bounded by _RUNTIME_CONTEXT_TAG and _RUNTIME_CONTEXT_END.
        end_marker = ContextBuilder._RUNTIME_CONTEXT_END
        end_pos = content.find(end_marker)
        if end_pos >= 0:
            stripped = content[end_pos + len(end_marker):].lstrip("\n")
        else:
            stripped = content[len(ContextBuilder._RUNTIME_CONTEXT_TAG):].lstrip("\n")
        return stripped if stripped.strip() else None

    # Hard cap on condensed subagent-result content persisted for
    # orchestrator sessions.  The full announce template embeds the complete
    # task prompt (often 1 000+ chars) plus the agent's full output — both
    # redundant once the orchestrator has already dispatched the next step.
    # Keeping a ≤ 600-char result summary dramatically shrinks replay
    # context without losing the information the LLM needs for future
    # orchestration decisions.
    _ORCHESTRATOR_RESULT_MAX_CHARS = 600

    def _persist_turn_usage(self, session: Session) -> None:
        """Append this turn's token usage to session metadata for later rollup.

        ``_last_usage`` is populated by ``_run_agent_loop`` from the LLM
        provider response.  We accumulate it into ``session.metadata["_turn_usage"]``
        so that ``_compute_session_rollups`` can sum input/output tokens across
        all turns without scanning message content.
        """
        usage = getattr(self, "_last_usage", None)
        if not usage:
            return
        prompt = usage.get("prompt_tokens", 0)
        completion = usage.get("completion_tokens", 0)
        cached = usage.get("cached_tokens", usage.get("cache_read_input_tokens", 0))
        if not (prompt or completion):
            return
        turn_list = session.metadata.setdefault("_turn_usage", [])
        if not isinstance(turn_list, list):
            turn_list = []
            session.metadata["_turn_usage"] = turn_list
        from datetime import datetime as _dt
        turn_list.append({
            "ts": _dt.now().isoformat(timespec="seconds"),
            "input": prompt,
            "output": completion,
            "cached": cached,
        })

    def _save_turn(self, session: Session, messages: list[dict], skip: int) -> None:
        """Save new-turn messages into session, truncating large tool results.

        Context-reduction strategies applied here:

        * ``reasoning_content`` / ``thinking_blocks`` are stripped from every
          persisted assistant message — the LLM's chain-of-thought from a
          completed turn is never needed in future replay; only the chosen
          actions (``tool_calls``) and their outcomes matter.
        * For **orchestrator** sessions, subagent-result content is condensed
          to status + truncated result, dropping the full task echo.
        """
        from datetime import datetime

        _is_orch = getattr(self, "is_orchestrator", False)

        for m in messages[skip:]:
            entry = dict(m)
            role, content = entry.get("role"), entry.get("content")
            # --- strip reasoning / thinking from assistant messages ----------
            if role == "assistant":
                entry.pop("reasoning_content", None)
                entry.pop("thinking_blocks", None)
            if role == "user" and entry.get("injected_event") == "subagent_result":
                if isinstance(content, str):
                    stripped = self._strip_runtime_context_from_content(content)
                    if stripped is None:
                        continue
                    # Orchestrator: condense subagent announce to status + result
                    if _is_orch:
                        stripped = self._condense_subagent_result(stripped)
                    entry["content"] = stripped
                elif isinstance(content, list):
                    filtered = self._sanitize_persisted_blocks(content, drop_runtime=True)
                    if not filtered:
                        continue
                    entry["content"] = filtered
                entry["role"] = "assistant"
                entry.setdefault("sender_id", "subagent")
                role = "assistant"
                content = entry.get("content")
            if role == "assistant" and not content and not entry.get("tool_calls"):
                continue  # skip empty assistant messages — they poison session context
            if role == "tool":
                if isinstance(content, str) and len(content) > self.max_tool_result_chars:
                    entry["content"] = truncate_text_fn(content, self.max_tool_result_chars)
                elif isinstance(content, list):
                    filtered = self._sanitize_persisted_blocks(content, should_truncate_text=True)
                    if not filtered:
                        continue
                    entry["content"] = filtered
            elif role == "user":
                if isinstance(content, str):
                    stripped = self._strip_runtime_context_from_content(content)
                    if stripped is None:
                        continue
                    entry["content"] = stripped
                if isinstance(content, list):
                    filtered = self._sanitize_persisted_blocks(content, drop_runtime=True)
                    if not filtered:
                        continue
                    entry["content"] = filtered
            entry.setdefault("timestamp", datetime.now().isoformat())
            session.messages.append(entry)
        session.updated_at = datetime.now()

    @classmethod
    def _condense_subagent_result(cls, content: str) -> str:
        """Condense a subagent announce for orchestrator replay.

        The full announce template includes the complete ``task`` description
        (often 1 000+ chars) which the orchestrator already knows from its own
        ``create_agent`` tool call.  We keep only the status header and a
        truncated result section.
        """
        # Extract result section (after "Result:\n")
        result_idx = content.find("\nResult:\n")
        if result_idx < 0:
            result_idx = content.find("\nResult:")
        if result_idx >= 0:
            header = content[: content.find("\n") + 1] if "\n" in content else content
            result = content[result_idx + len("\nResult:\n"):]
        else:
            header = content[: content.find("\n") + 1] if "\n" in content else content
            result = content

        max_chars = cls._ORCHESTRATOR_RESULT_MAX_CHARS
        if len(result) > max_chars:
            result = result[:max_chars] + "\n… [truncated]"
        return f"{header}\nResult:\n{result}"

    def _persist_subagent_followup(self, session: Session, msg: InboundMessage) -> bool:
        """Persist subagent follow-ups before prompt assembly so history stays durable.

        Returns True if a new entry was appended; False if the follow-up was
        deduped (same ``subagent_task_id`` already in session) or carries no
        content worth persisting.
        """
        if not msg.content:
            return False
        task_id = msg.metadata.get("subagent_task_id") if isinstance(msg.metadata, dict) else None
        if task_id and any(
            m.get("injected_event") == "subagent_result" and m.get("subagent_task_id") == task_id
            for m in session.messages
        ):
            return False
        session.add_message(
            "assistant",
            msg.content,
            sender_id=msg.sender_id,
            injected_event="subagent_result",
            subagent_task_id=task_id,
        )
        return True

    def _set_runtime_checkpoint(self, session: Session, payload: dict[str, Any]) -> None:
        """Persist the latest in-flight turn state into session metadata."""
        session.metadata[self._RUNTIME_CHECKPOINT_KEY] = payload
        self.sessions.save(session)

    def _mark_pending_user_turn(self, session: Session) -> None:
        session.metadata[self._PENDING_USER_TURN_KEY] = True

    def _clear_pending_user_turn(self, session: Session) -> None:
        session.metadata.pop(self._PENDING_USER_TURN_KEY, None)

    def _clear_runtime_checkpoint(self, session: Session) -> None:
        if self._RUNTIME_CHECKPOINT_KEY in session.metadata:
            session.metadata.pop(self._RUNTIME_CHECKPOINT_KEY, None)

    @staticmethod
    def _checkpoint_message_key(message: dict[str, Any]) -> tuple[Any, ...]:
        return (
            message.get("role"),
            message.get("content"),
            message.get("tool_call_id"),
            message.get("name"),
            message.get("tool_calls"),
            message.get("reasoning_content"),
            message.get("thinking_blocks"),
        )

    def _restore_runtime_checkpoint(self, session: Session) -> bool:
        """Materialize an unfinished turn into session history before a new request."""
        from datetime import datetime

        checkpoint = session.metadata.get(self._RUNTIME_CHECKPOINT_KEY)
        if not isinstance(checkpoint, dict):
            return False

        assistant_message = checkpoint.get("assistant_message")
        completed_tool_results = checkpoint.get("completed_tool_results") or []
        pending_tool_calls = checkpoint.get("pending_tool_calls") or []

        restored_messages: list[dict[str, Any]] = []
        if isinstance(assistant_message, dict):
            restored = dict(assistant_message)
            restored.setdefault("timestamp", datetime.now().isoformat())
            restored_messages.append(restored)
        for message in completed_tool_results:
            if isinstance(message, dict):
                restored = dict(message)
                restored.setdefault("timestamp", datetime.now().isoformat())
                restored_messages.append(restored)
        for tool_call in pending_tool_calls:
            if not isinstance(tool_call, dict):
                continue
            tool_id = tool_call.get("id")
            name = ((tool_call.get("function") or {}).get("name")) or "tool"
            restored_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_id,
                    "name": name,
                    "content": "Error: Task interrupted before this tool finished.",
                    "timestamp": datetime.now().isoformat(),
                }
            )

        overlap = 0
        max_overlap = min(len(session.messages), len(restored_messages))
        for size in range(max_overlap, 0, -1):
            existing = session.messages[-size:]
            restored = restored_messages[:size]
            if all(
                self._checkpoint_message_key(left) == self._checkpoint_message_key(right)
                for left, right in zip(existing, restored)
            ):
                overlap = size
                break
        session.messages.extend(restored_messages[overlap:])

        self._clear_pending_user_turn(session)
        self._clear_runtime_checkpoint(session)
        return True

    def _restore_pending_user_turn(self, session: Session) -> bool:
        """Close a turn that only persisted the user message before crashing."""
        from datetime import datetime

        if not session.metadata.get(self._PENDING_USER_TURN_KEY):
            return False

        if session.messages and session.messages[-1].get("role") == "user":
            session.messages.append(
                {
                    "role": "assistant",
                    "content": "Error: Task interrupted before a response was generated.",
                    "timestamp": datetime.now().isoformat(),
                }
            )
            session.updated_at = datetime.now()

        self._clear_pending_user_turn(session)
        return True

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
        media: list[str] | None = None,
        on_progress: Callable[..., Awaitable[None]] | None = None,
        on_stream: Callable[[str], Awaitable[None]] | None = None,
        on_stream_end: Callable[..., Awaitable[None]] | None = None,
    ) -> OutboundMessage | None:
        """Process a message directly and return the outbound payload."""
        await self._connect_mcp()
        msg = InboundMessage(
            channel=channel, sender_id="user", chat_id=chat_id,
            content=content, media=media or [],
        )
        return await self._process_message(
            msg,
            session_key=session_key,
            on_progress=on_progress,
            on_stream=on_stream,
            on_stream_end=on_stream_end,
        )

"""Subagent manager for background task execution."""

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

from secbot.agent.asset_feed import AssetFeed, AssetFeedRegistry
from secbot.agent.blackboard import Blackboard, BlackboardRegistry
from secbot.agent.hook import AgentHook, AgentHookContext
from secbot.agent.runner import AgentRunner, AgentRunSpec
from secbot.agent.skills import BUILTIN_SKILLS_DIR
from secbot.agent.tools.ask import AskUserTool
from secbot.agent.tools.asset_feed import AssetPushTool, ReadAssetsTool
from secbot.agent.tools.blackboard import BlackboardReadTool, BlackboardWriteTool
from secbot.agent.tools.curl import CurlTool
from secbot.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from secbot.agent.tools.registry import ToolRegistry
from secbot.agent.tools.report_vulnerability import ReportVulnerabilityTool
from secbot.agent.tools.search import GlobTool, GrepTool
from secbot.agent.tools.shell import ExecTool
from secbot.agent.tools.skill import (
    bind_skill_context,
    current_asset_auto_management_enabled,
    current_scan_id,
    current_skill_confirm,
    discover_skill_tools,
)
from secbot.agent.vulnerability_store import VulnerabilityStore, VulnerabilityStoreRegistry
from secbot.bus.events import InboundMessage
from secbot.bus.queue import MessageBus
from secbot.config.schema import AgentDefaults, ExecToolConfig, WebToolsConfig
from secbot.providers.base import LLMProvider
from secbot.utils.prompt_templates import render_template

if TYPE_CHECKING:
    from secbot.agents.registry import AgentRegistry, ExpertAgentSpec


# _MAX_INTERRUPT_RETRIES removed (v2): auto-retry with a fresh context caused
# agents to re-run expensive tools (e.g. katana). Incomplete results are now
# always reported to the orchestrator for intelligent re-dispatch.


@dataclass(slots=True)
class SubagentStatus:
    """Real-time status of a running subagent."""

    task_id: str
    label: str
    task_description: str
    started_at: float          # time.monotonic()
    phase: str = "initializing"  # initializing | awaiting_tools | tools_completed | final_response | done | error
    iteration: int = 0
    tool_events: list = field(default_factory=list)   # [{name, status, detail}, ...]
    usage: dict = field(default_factory=dict)          # token usage
    stop_reason: str | None = None
    error: str | None = None
    # Number of automatic re-dispatches after iteration/context interrupts.
    retries: int = 0
    # Wall-clock timestamp (epoch seconds) of the last heartbeat — refreshed
    # on every checkpoint and lifecycle transition. Surfaced over
    # ``GET /api/agents?include_status=true`` and the ``agent_status`` event.
    last_heartbeat_at: float = field(default_factory=time.time)
    # Resolved expert-agent registry name when ``spawn(agent=...)`` was used.
    # Empty for ad-hoc subagents. ``/api/agents?include_status=true`` keys
    # status off this field so the runtime row matches a registry row.
    agent_name: str = ""
    # Effective parent session key. Kept on the retained status row after the
    # running-task index is cleaned up so orchestration tools can still report
    # recently completed children for the current chat/session.
    session_key: str = ""


class _SubagentHook(AgentHook):
    """Hook for subagent execution.

    Two responsibilities:

    1. Mirror iteration/tool events back into :class:`SubagentStatus` so the
       manager can expose real-time progress.
    2. When ``broadcast_fn`` is wired, emit structured ``tool_call`` events
       (running/critical -> ok/error) so the front-end can render per-tool
       folding cards keyed by ``tool_call_id``. Spec:
       ``.trellis/tasks/05-12-multi-agent-obs-tool-call/prd.md`` §B5.
    """

    def __init__(
        self,
        task_id: str,
        status: SubagentStatus | None = None,
        *,
        broadcast_fn: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
        agent_name: str = "",
        critical_tool_names: set[str] | None = None,
    ) -> None:
        super().__init__()
        self._task_id = task_id
        self._status = status
        self._broadcast_fn = broadcast_fn
        self._agent_name = agent_name
        self._critical_tool_names: set[str] = set(critical_tool_names or ())
        self._start_times: dict[str, float] = {}

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        now = time.monotonic()
        for tool_call in context.tool_calls:
            args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
            logger.debug(
                "Subagent [{}] executing: {} with arguments: {}",
                self._task_id, tool_call.name, args_str,
            )
            self._start_times[tool_call.id] = now
            if self._broadcast_fn is None:
                continue
            is_critical = tool_call.name in self._critical_tool_names
            await self._broadcast_fn(
                "tool_call",
                {
                    "task_id": self._task_id,
                    "agent_name": self._agent_name,
                    "tool_call_id": tool_call.id,
                    "tool_name": tool_call.name,
                    "tool_args": tool_call.arguments,
                    "status": "critical" if is_critical else "running",
                    "is_critical": is_critical,
                },
            )

    async def after_iteration(self, context: AgentHookContext) -> None:
        if self._status is not None:
            self._status.iteration = context.iteration
            self._status.tool_events = list(context.tool_events)
            self._status.usage = dict(context.usage)
            if context.error:
                self._status.error = str(context.error)

        if self._broadcast_fn is None:
            return

        now = time.monotonic()
        for idx, tool_call in enumerate(context.tool_calls):
            event = (
                context.tool_events[idx]
                if idx < len(context.tool_events)
                else None
            )
            if event is None:
                continue
            # ``waiting`` means the tool paused for user input (AskUserTool);
            # the terminal frame will arrive on a later iteration.
            if event.get("status") == "waiting":
                continue
            tool_result = (
                context.tool_results[idx]
                if idx < len(context.tool_results)
                else None
            )
            start = self._start_times.pop(tool_call.id, None)
            duration_ms = (
                int((now - start) * 1000) if start is not None else None
            )
            is_critical = tool_call.name in self._critical_tool_names
            status, reason = self._classify_terminal(event, tool_result)
            payload: dict[str, Any] = {
                "task_id": self._task_id,
                "agent_name": self._agent_name,
                "tool_call_id": tool_call.id,
                "tool_name": tool_call.name,
                "tool_args": tool_call.arguments,
                "status": status,
                "is_critical": is_critical,
            }
            if duration_ms is not None:
                payload["duration_ms"] = duration_ms
            if reason:
                payload["reason"] = reason
            detail = event.get("detail")
            if detail:
                payload["detail"] = detail
            await self._broadcast_fn("tool_call", payload)

    @staticmethod
    def _classify_terminal(
        event: dict[str, str],
        tool_result: Any,
    ) -> tuple[str, str | None]:
        """Map a raw ``tool_event`` + tool result string to (status, reason).

        Critical skills short-circuit on user deny / timeout by returning a
        normal :class:`SkillResult` with ``summary.user_denied=True`` — from
        the runner's perspective the tool succeeded. We normalise that into a
        terminal ``error`` frame with a user-visible reason so the UI can
        render the denied badge (spec: ``frontend/component-patterns.md``
        §3.2).
        """
        raw_status = event.get("status", "ok")
        if raw_status == "error":
            return "error", None
        if isinstance(tool_result, str) and '"user_denied"' in tool_result:
            try:
                parsed = json.loads(tool_result)
            except ValueError:
                parsed = None
            summary = (parsed or {}).get("summary") if isinstance(parsed, dict) else None
            if isinstance(summary, dict) and summary.get("user_denied"):
                raw_reason = summary.get("reason") or "denied"
                reason = {
                    "denied": "user_denied",
                    "confirm_timeout": "timeout",
                }.get(str(raw_reason), str(raw_reason))
                return "error", reason
        return "ok", None


def _normalise_endpoint_key(endpoint_url: str, endpoint_param: str) -> tuple[str, str]:
    """Compute the deduplication key for endpoint-level mutual exclusion (D5).

    Goal: two ``create_agent`` calls naming the *same* endpoint must collide
    even if their URL forms differ in trivial ways (case, trailing slash,
    default port, query/fragment). We deliberately drop the query string &
    fragment so that ``http://h/path?foo=1`` and ``http://h/path?bar=2``
    share a lock — the parameter being probed is captured separately via
    ``endpoint_param``.
    """
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(endpoint_url.strip())
    scheme = (parts.scheme or "").lower()
    host = (parts.hostname or "").lower()
    port = parts.port
    # Drop the default port for the scheme so ``http://h:80/`` == ``http://h/``.
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        port = None
    netloc = host if port is None else f"{host}:{port}"
    if parts.username or parts.password:
        userinfo = parts.username or ""
        if parts.password is not None:
            userinfo = f"{userinfo}:{parts.password}"
        netloc = f"{userinfo}@{netloc}"
    path = parts.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/") or "/"
    normalised_url = urlunsplit((scheme, netloc, path, "", ""))
    return (normalised_url, endpoint_param.strip().lower())


class SubagentManager:
    """Manages background subagent execution."""

    def __init__(
        self,
        provider: LLMProvider,
        workspace: Path,
        bus: MessageBus,
        max_tool_result_chars: int,
        model: str | None = None,
        web_config: "WebToolsConfig | None" = None,
        exec_config: "ExecToolConfig | None" = None,
        restrict_to_workspace: bool = False,
        disabled_skills: list[str] | None = None,
        max_iterations: int | None = None,
        agent_registry: "AgentRegistry | None" = None,
        blackboard: Blackboard | None = None,
        blackboard_registry: "BlackboardRegistry | None" = None,
        asset_feed_registry: "AssetFeedRegistry | None" = None,
        vulnerability_store_registry: "VulnerabilityStoreRegistry | None" = None,
        parent_result_callback: Callable[[InboundMessage], Awaitable[bool]] | None = None,
    ):
        defaults = AgentDefaults()
        self.provider = provider
        self.workspace = workspace
        self.bus = bus
        self.model = model or provider.get_default_model()
        self.web_config = web_config or WebToolsConfig()
        self.max_tool_result_chars = max_tool_result_chars
        self.exec_config = exec_config or ExecToolConfig()
        self.restrict_to_workspace = restrict_to_workspace
        self.disabled_skills = set(disabled_skills or [])
        self.max_iterations = (
            max_iterations
            if max_iterations is not None
            else defaults.max_tool_iterations
        )
        self.max_concurrent_subagents = defaults.max_concurrent_subagents
        self.runner = AgentRunner(provider)
        # ``blackboard`` is the default per-process board used when no
        # registry / origin_chat_id is supplied (e.g. legacy tests). When a
        # ``blackboard_registry`` is wired through (production AgentLoop),
        # ``_run_subagent`` resolves the chat-scoped board from it instead.
        self.blackboard = blackboard or Blackboard()
        self.blackboard_registry = blackboard_registry
        self._parent_result_callback = parent_result_callback
        # ``asset_feed_registry`` is the chat-scoped real-time discovery
        # channel (URL / port / vuln / ...). When None, sub-agents still
        # boot but ``asset_push`` / ``read_assets`` are not registered.
        self.asset_feed_registry = asset_feed_registry
        # ``vulnerability_store_registry`` is the chat-scoped structured
        # vulnerability store. When None, ``report_vulnerability`` is not
        # registered for sub-agents.
        self.vulnerability_store_registry = vulnerability_store_registry
        # PR3: optional expert-agent registry. When present, ``spawn(agent=...)``
        # resolves the named spec and ``_run_subagent`` filters the skill tool
        # set down to ``spec.scoped_skills``.
        self.agent_registry: "AgentRegistry | None" = agent_registry
        self._running_tasks: dict[str, asyncio.Task[None]] = {}
        self._task_statuses: dict[str, SubagentStatus] = {}
        self._session_tasks: dict[str, set[str]] = {}  # session_key -> {task_id, ...}
        # D5 endpoint-level mutex: maps normalised ``(endpoint_url, endpoint_param)``
        # tuples to the task_id that currently owns them. ``spawn`` rejects a
        # second endpoint-bound subagent targeting the same key; the per-task
        # cleanup callback releases the entry on completion / failure.
        self._endpoint_inflight: dict[tuple[str, str], str] = {}

    def set_provider(self, provider: LLMProvider, model: str) -> None:
        self.provider = provider
        self.model = model
        self.runner.provider = provider

    async def _broadcast_agent_event(
        self,
        origin: dict[str, str],
        type: str,
        payload: dict[str, Any],
    ) -> None:
        """Best-effort broadcast of an agent_event frame to the WebSocket channel."""
        if origin.get("channel") != "websocket":
            return
        from secbot.channels.websocket import WebSocketChannel

        channel = WebSocketChannel.get_active_instance()
        if channel is None:
            return
        chat_id = origin.get("chat_id", "direct")
        try:
            await channel.broadcast_agent_event(
                chat_id=chat_id,
                type=type,
                payload=payload,
            )
        except Exception:
            logger.debug("agent_event ({}) broadcast failed", type, exc_info=True)

    async def _broadcast_agent_status(
        self,
        origin: dict[str, str],
        *,
        agent_name: str,
        status: str,
        current_task_id: str | None,
        last_heartbeat_at: float | None = None,
    ) -> None:
        """Broadcast an ``agent_event.type='agent_status'`` lifecycle event.

        Sent on every spawn / checkpoint / done / error transition so the
        Sidebar agent chip can transition without polling. Frequency is
        bounded by the underlying lifecycle (no extra throttle needed).
        """
        from datetime import datetime, timezone

        ts = last_heartbeat_at if last_heartbeat_at is not None else time.time()
        await self._broadcast_agent_event(
            origin=origin,
            type="agent_status",
            payload={
                "agent_name": agent_name,
                "status": status,
                "current_task_id": current_task_id,
                "last_heartbeat_at": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds"),
            },
        )

    async def spawn(
        self,
        task: str,
        label: str | None = None,
        origin_channel: str = "cli",
        origin_chat_id: str = "direct",
        session_key: str | None = None,
        origin_message_id: str | None = None,
        agent: str | None = None,
        target: str | None = None,
        endpoint_url: str | None = None,
        endpoint_param: str | None = None,
    ) -> str:
        """Spawn a subagent to execute a task in the background.

        ``target`` / ``endpoint_url`` / ``endpoint_param`` are routing/audit
        metadata supplied by ``SpawnTool``; they are NOT auto-injected into
        the LLM prompt (the Orchestrator is expected to embed them into
        ``task`` when relevant). ``endpoint_url`` + ``endpoint_param`` are
        also used to derive the endpoint-level mutex key for D5 enforcement.
        """
        task_id = str(uuid.uuid4())[:8]
        display_label = label or task[:30] + ("..." if len(task) > 30 else "")
        origin = {"channel": origin_channel, "chat_id": origin_chat_id, "session_key": session_key}

        # Resolve expert-agent spec up-front so _run_subagent can pre-filter
        # tools. Validation already happened in SpawnTool; we still guard here
        # so programmatic callers (tests) can't mis-route.
        spec: "ExpertAgentSpec | None" = None
        if agent:
            if self.agent_registry is None or agent not in self.agent_registry:
                return (
                    f"Unknown expert agent '{agent}'. "
                    "SubagentManager has no registry attached."
                )
            spec = self.agent_registry.get(agent)

        # D5: endpoint-level mutual exclusion. We only enforce when BOTH
        # endpoint fields are present (SpawnTool already guarantees this is
        # the case iff the resolved spec is endpoint_bound). Programmatic
        # callers that bypass SpawnTool simply opt out by not passing them.
        endpoint_key: tuple[str, str] | None = None
        if endpoint_url and endpoint_param:
            endpoint_key = _normalise_endpoint_key(endpoint_url, endpoint_param)
            holder = self._endpoint_inflight.get(endpoint_key)
            if holder is not None:
                return (
                    f"create_agent failed: endpoint already busy — another "
                    f"subagent (task {holder}) is currently running against "
                    f"endpoint {endpoint_key[0]}?{endpoint_key[1]}. Wait for "
                    "it to finish before launching another."
                )

        status = SubagentStatus(
            task_id=task_id,
            label=display_label,
            task_description=task,
            started_at=time.monotonic(),
            agent_name=(agent or ""),
            session_key=session_key or "",
        )
        self._task_statuses[task_id] = status
        if endpoint_key is not None:
            self._endpoint_inflight[endpoint_key] = task_id

        bg_task = asyncio.create_task(
            self._run_subagent(task_id, task, display_label, origin, status, origin_message_id, spec)
        )
        self._running_tasks[task_id] = bg_task
        if session_key:
            self._session_tasks.setdefault(session_key, set()).add(task_id)

        def _cleanup(_: asyncio.Task) -> None:
            self._running_tasks.pop(task_id, None)
            # Delay removal from _task_statuses so that completed/error
            # snapshots remain visible in HTTP polls for a short window.
            loop = asyncio.get_running_loop()
            loop.call_later(60, self._task_statuses.pop, task_id, None)
            if session_key and (ids := self._session_tasks.get(session_key)):
                ids.discard(task_id)
                if not ids:
                    del self._session_tasks[session_key]
            # D5: release the endpoint mutex as soon as the bg task is done
            # (regardless of success/error), but only if WE still own it.
            if endpoint_key is not None and self._endpoint_inflight.get(endpoint_key) == task_id:
                self._endpoint_inflight.pop(endpoint_key, None)

        bg_task.add_done_callback(_cleanup)

        logger.info("Spawned subagent [{}]: {}", task_id, display_label)
        await self._broadcast_agent_event(
            origin={"channel": origin_channel, "chat_id": origin_chat_id},
            type="subagent_spawned",
            payload={
                "task_id": task_id,
                "agent_name": agent or display_label,
                "label": display_label,
                "task_description": task,
            },
        )
        # Notify the sidebar that this expert agent is now running. The
        # ``agent_name`` is the resolved expert spec name when ``spawn(agent=...)``
        # was used; otherwise we fall back to the display label so the chip
        # at least appears for ad-hoc subagents.
        await self._broadcast_agent_status(
            origin={"channel": origin_channel, "chat_id": origin_chat_id},
            agent_name=(agent or display_label),
            status="running",
            current_task_id=task_id,
            last_heartbeat_at=status.last_heartbeat_at,
        )
        return f"Subagent [{display_label}] started (id: {task_id}). I'll notify you when it completes."

    async def _run_subagent(
        self,
        task_id: str,
        task: str,
        label: str,
        origin: dict[str, str],
        status: SubagentStatus,
        origin_message_id: str | None = None,
        spec: "ExpertAgentSpec | None" = None,
    ) -> None:
        """Execute the subagent task and announce the result."""
        logger.info("Subagent [{}] starting task: {}", task_id, label)

        # Resolve the chat-scoped blackboard, falling back to the per-manager
        # default when no registry is wired or the chat_id is missing. We do
        # this once at the top of the run so all tools / hooks share the same
        # Blackboard instance for this subagent's lifetime.
        chat_id = origin.get("chat_id") or "direct"
        if self.blackboard_registry is not None:
            resolved_blackboard = await self.blackboard_registry.get_or_create(chat_id)
        else:
            resolved_blackboard = self.blackboard
        if self.asset_feed_registry is not None:
            resolved_asset_feed: AssetFeed | None = (
                await self.asset_feed_registry.get_or_create(chat_id)
            )
        else:
            resolved_asset_feed = None
        # Resolve the chat-scoped vulnerability store for report_vulnerability.
        if self.vulnerability_store_registry is not None:
            resolved_vuln_store: VulnerabilityStore | None = (
                await self.vulnerability_store_registry.get_or_create(chat_id)
            )
        else:
            resolved_vuln_store = None

        async def _on_checkpoint(payload: dict) -> None:
            status.phase = payload.get("phase", status.phase)
            status.iteration = payload.get("iteration", status.iteration)
            status.last_heartbeat_at = time.time()
            await self._broadcast_agent_event(
                origin=origin,
                type="subagent_status",
                payload={
                    "task_id": task_id,
                    "phase": status.phase,
                    "iteration": status.iteration,
                    "tool_events": status.tool_events,
                },
            )
            # Liveness ping for the sidebar — same lifecycle, lighter shape.
            await self._broadcast_agent_status(
                origin=origin,
                agent_name=(spec.name if spec is not None else label),
                status="running",
                current_task_id=task_id,
                last_heartbeat_at=status.last_heartbeat_at,
            )

        resolved_agent_name = spec.name if spec is not None else label
        try:
            # Build subagent tools (no message tool, no spawn tool)
            tools = ToolRegistry()
            # ``minimal_tools`` agents receive ONLY their scoped SkillTools —
            # no file / curl / blackboard / ask_user / exec / asset_feed.
            # This hard-guards the tool surface so an agent like ``report``
            # can never wander into unrelated tools (e.g. curl→sqlite3).
            _minimal = spec is not None and spec.minimal_tools
            if not _minimal:
                allowed_dir = self.workspace if (self.restrict_to_workspace or self.exec_config.sandbox) else None
                extra_read = [BUILTIN_SKILLS_DIR] if BUILTIN_SKILLS_DIR.exists() else None
                # Subagent gets its own FileStates so its read-dedup cache is
                # isolated from the parent loop's sessions (issue #3571).
                from secbot.agent.tools.file_state import FileStates
                file_states = FileStates()
                tools.register(ReadFileTool(workspace=self.workspace, allowed_dir=allowed_dir, extra_allowed_dirs=extra_read, file_states=file_states))
                tools.register(WriteFileTool(workspace=self.workspace, allowed_dir=allowed_dir, file_states=file_states))
                tools.register(EditFileTool(workspace=self.workspace, allowed_dir=allowed_dir, file_states=file_states))
                tools.register(ListDirTool(workspace=self.workspace, allowed_dir=allowed_dir, file_states=file_states))
                tools.register(GlobTool(workspace=self.workspace, allowed_dir=allowed_dir, file_states=file_states))
                tools.register(GrepTool(workspace=self.workspace, allowed_dir=allowed_dir, file_states=file_states))
                tools.register(AskUserTool())
                tools.register(BlackboardWriteTool(blackboard=resolved_blackboard, agent_name=resolved_agent_name))
                tools.register(BlackboardReadTool(blackboard=resolved_blackboard))
                if resolved_asset_feed is not None:
                    tools.register(
                        AssetPushTool(
                            feed=resolved_asset_feed,
                            bus=self.bus,
                            origin=origin,
                            agent_name=resolved_agent_name,
                        )
                    )
                    tools.register(ReadAssetsTool(feed=resolved_asset_feed))
                # report_vulnerability: structured vulnerability reporting
                # writes to both VulnerabilityStore and AssetFeed (dual-write).
                if resolved_vuln_store is not None:
                    tools.register(
                        ReportVulnerabilityTool(
                            store=resolved_vuln_store,
                            feed=resolved_asset_feed,
                            agent_name=resolved_agent_name,
                        )
                    )
                # ExecTool is gated by BOTH global exec_config.enable AND per-agent
                # allow_exec. Default-deny: subagents without an explicit opt-in
                # ExpertAgentSpec, or with allow_exec=False, NEVER receive exec.
                if self.exec_config.enable and spec is not None and spec.allow_exec:
                    tools.register(
                        ExecTool(
                            timeout=self.exec_config.timeout,
                            deny_patterns=self.exec_config.deny_patterns,
                            allow_patterns=self.exec_config.allow_patterns,
                            restrict_to_workspace=self.restrict_to_workspace,
                            sandbox=self.exec_config.sandbox,
                            path_append=self.exec_config.path_append,
                            allowed_env_keys=self.exec_config.allowed_env_keys,
                        )
                    )
                tools.register(CurlTool())
            # Subagents also get SkillTool instances so they can run qscan /
            # fscan / etc. without shelling out. When an expert-agent spec is
            # provided (``spawn(agent=...)``), restrict the SkillTool set to
            # that spec's ``scoped_skills`` so the subagent only sees tools
            # relevant to its role.
            scoped: set[str] | None = (
                set(spec.scoped_skills) if spec is not None else None
            )
            critical_tool_names: set[str] = set()
            for skill_tool in discover_skill_tools(
                BUILTIN_SKILLS_DIR,
                workspace=self.workspace,
            ):
                if scoped is not None and skill_tool.name not in scoped:
                    continue
                tools.register(skill_tool)
                if skill_tool._meta.is_critical():
                    critical_tool_names.add(skill_tool.name)
            # Inherit the parent loop's per-turn SkillContext binding so raw
            # logs and scan_id stay consistent across parent + children.
            # Crucially, preserve the ``confirm`` callback so critical skills
            # inside the subagent still surface the WebUI approval dialog.
            parent_confirm = current_skill_confirm()
            parent_asset_auto_management = current_asset_auto_management_enabled()
            # Inherit the parent loop's scan_id so scan artifacts and
            # optional CMDB writes from orchestrator + subagents share one
            # scan identity. report-html also uses this id to locate the
            # persisted session JSONL. scan_dir uses scan_id (not task_id)
            # so raw logs and reports are grouped under one folder per chat:
            # .secbot/scans/<scan_id>/.
            parent_scan_id = current_scan_id()
            bind_skill_context(
                scan_id=parent_scan_id,
                scan_dir=self.workspace / ".secbot" / "scans" / parent_scan_id,
                confirm=parent_confirm,
                asset_auto_management_enabled=parent_asset_auto_management,
                asset_feed=resolved_asset_feed,
                vulnerability_store=resolved_vuln_store,
            )
            system_prompt = self._build_subagent_prompt(spec)
            # D3: the shared-blackboard snapshot is NO LONGER auto-injected
            # into the subagent's system prompt. The orchestrator owns prompt
            # composition (it can read the blackboard via ``read_blackboard``
            # and embed the relevant excerpt into ``task``). The subagent can
            # still call ``read_blackboard`` / ``blackboard_write`` if needed.
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task},
            ]

            async def _broadcast_tool_event(
                type_: str, payload: dict[str, Any]
            ) -> None:
                await self._broadcast_agent_event(
                    origin=origin, type=type_, payload=payload
                )

            # Respect per-agent max_iterations from the YAML spec, capped
            # at the global limit so a misconfigured agent can't exceed the
            # system-wide safety ceiling.
            _effective_max_iter = (
                min(self.max_iterations, spec.max_iterations)
                if spec is not None
                else self.max_iterations
            )

            result = await self.runner.run(AgentRunSpec(
                initial_messages=messages,
                tools=tools,
                model=self.model,
                max_iterations=_effective_max_iter,
                max_tool_result_chars=self.max_tool_result_chars,
                hook=_SubagentHook(
                    task_id,
                    status,
                    broadcast_fn=_broadcast_tool_event,
                    agent_name=resolved_agent_name,
                    critical_tool_names=critical_tool_names,
                ),
                max_iterations_message="Task completed but no final response was generated.",
                error_message=None,
                fail_on_tool_error=False,
                checkpoint_callback=_on_checkpoint,
            ))
            # No automatic retry on max_iterations / context_exhausted.
            # The runner already generates a structured interrupt summary;
            # we report it to the orchestrator which has full context to
            # decide whether to re-dispatch the agent. Auto-retrying with
            # a fresh context caused the agent to re-run expensive tools
            # (e.g. katana) because it lacked the original tool results.
            status.phase = "done"
            status.stop_reason = result.stop_reason

            if result.stop_reason == "tool_error":
                status.tool_events = list(result.tool_events)
                await self._announce_result(
                    task_id, label, task,
                    self._format_partial_progress(result),
                    origin, "error", origin_message_id,
                    agent_name=resolved_agent_name,
                )
                await self._broadcast_agent_status(
                    origin=origin,
                    agent_name=resolved_agent_name,
                    status="error",
                    current_task_id=None,
                )
            elif result.stop_reason == "error":
                await self._announce_result(
                    task_id, label, task,
                    result.error or "Error: subagent execution failed.",
                    origin, "error", origin_message_id,
                    agent_name=resolved_agent_name,
                )
                await self._broadcast_agent_status(
                    origin=origin,
                    agent_name=resolved_agent_name,
                    status="error",
                    current_task_id=None,
                )
            elif result.stop_reason in ("max_iterations", "context_exhausted"):
                # Interrupted: report with incomplete status so the orchestrator
                # can decide whether to re-dispatch with adjusted parameters.
                interrupt_summary = (
                    result.final_content
                    or f"Subagent interrupted ({result.stop_reason}): "
                       "no summary available."
                )
                reason_label = (
                    "工具调用轮次耗尽" if result.stop_reason == "max_iterations"
                    else "上下文窗口已满"
                )
                logger.warning(
                    "Subagent [{}] interrupted: {} — reporting incomplete to orchestrator",
                    task_id, reason_label,
                )
                await self._announce_result(
                    task_id, label, task,
                    f"[任务未完成 — {reason_label}]\n\n{interrupt_summary}",
                    origin, "incomplete", origin_message_id,
                    agent_name=resolved_agent_name,
                )
                await self._broadcast_agent_status(
                    origin=origin,
                    agent_name=resolved_agent_name,
                    status="interrupted",
                    current_task_id=None,
                )
            else:
                final_result = result.final_content or "Task completed but no final response was generated."
                logger.info("Subagent [{}] completed successfully", task_id)
                await self._announce_result(
                    task_id, label, task, final_result, origin, "ok", origin_message_id,
                    agent_name=resolved_agent_name,
                )
                await self._broadcast_agent_status(
                    origin=origin,
                    agent_name=resolved_agent_name,
                    status="completed",
                    current_task_id=None,
                )

        except Exception as e:
            status.phase = "error"
            status.stop_reason = "error"
            status.error = str(e)
            logger.exception("Subagent [{}] failed", task_id)
            await self._announce_result(
                task_id, label, task, f"Error: {e}", origin, "error", origin_message_id,
                agent_name=resolved_agent_name,
            )
            await self._broadcast_agent_status(
                origin=origin,
                agent_name=resolved_agent_name,
                status="error",
                current_task_id=None,
            )

    async def _announce_result(
        self,
        task_id: str,
        label: str,
        task: str,
        result: str,
        origin: dict[str, str],
        status: str,
        origin_message_id: str | None = None,
        agent_name: str | None = None,
    ) -> None:
        """Announce the subagent result to the main agent via the message bus."""
        if status == "ok":
            status_text = "completed successfully"
        elif status == "incomplete":
            status_text = "interrupted (task not completed — see summary below)"
        else:
            status_text = "failed"

        announce_content = render_template(
            "agent/subagent_announce.md",
            label=label,
            status_text=status_text,
            task=task,
            result=result,
        )

        # Inject as system message to trigger main agent.
        # Use session_key_override to align with the main agent's effective
        # session key (which accounts for unified sessions) so the result is
        # routed to the correct pending queue (mid-turn injection) instead of
        # being dispatched as a competing independent task.
        override = origin.get("session_key") or f"{origin['channel']}:{origin['chat_id']}"
        metadata: dict[str, Any] = {
            "injected_event": "subagent_result",
            "subagent_task_id": task_id,
        }
        if origin_message_id:
            metadata["origin_message_id"] = origin_message_id
        msg = InboundMessage(
            channel="system",
            sender_id=agent_name or label,
            chat_id=f"{origin['channel']}:{origin['chat_id']}",
            content=announce_content,
            session_key_override=override,
            metadata=metadata,
        )

        delivered = False
        if self._parent_result_callback is not None:
            try:
                delivered = await self._parent_result_callback(msg)
            except Exception:
                logger.exception(
                    "Subagent [{}] direct result delivery failed; falling back to bus",
                    task_id,
                )
                delivered = False
        if not delivered:
            await self.bus.publish_inbound(msg)
        await self._broadcast_agent_event(
            origin=origin,
            type="subagent_done",
            payload={
                "task_id": task_id,
                "agent_name": agent_name or label,
                "label": label,
                "status": status,
                "result": result,
            },
        )
        logger.debug("Subagent [{}] announced result to {}:{}", task_id, origin['channel'], origin['chat_id'])

    @staticmethod
    def _format_partial_progress(result) -> str:
        completed = [e for e in result.tool_events if e["status"] == "ok"]
        failure = next((e for e in reversed(result.tool_events) if e["status"] == "error"), None)
        lines: list[str] = []
        if completed:
            lines.append("Completed steps:")
            for event in completed[-3:]:
                lines.append(f"- {event['name']}: {event['detail']}")
        if failure:
            if lines:
                lines.append("")
            lines.append("Failure:")
            lines.append(f"- {failure['name']}: {failure['detail']}")
        if result.error and not failure:
            if lines:
                lines.append("")
            lines.append("Failure:")
            lines.append(f"- {result.error}")
        return "\n".join(lines) or (result.error or "Error: subagent execution failed.")

    def _build_subagent_prompt(
        self, spec: "ExpertAgentSpec | None" = None
    ) -> str:
        """Build the system prompt for an expert subagent.

        Composition:

        - runtime/time context
        - workspace path
        - hard rules (skill-tool preference + missing-skill → blackboard
          blocker + return)
        - untrusted-content snippet
        - SKILL.md self-inspection hint

        Expert-specific routing and execution instructions are NOT appended
        here. The Orchestrator owns prompt composition and must pass the full
        task body as the subagent's user message.
        """
        from secbot.agent.context import ContextBuilder

        time_ctx = ContextBuilder._build_runtime_context(None, None)
        return render_template(
            "agent/subagent_system.md",
            time_ctx=time_ctx,
            workspace=str(self.workspace),
            skills_dir=str(BUILTIN_SKILLS_DIR),
        )

    async def cancel_by_session(self, session_key: str) -> int:
        """Cancel all subagents for the given session. Returns count cancelled."""
        tasks = [self._running_tasks[tid] for tid in self._session_tasks.get(session_key, [])
                 if tid in self._running_tasks and not self._running_tasks[tid].done()]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        return len(tasks)

    def get_running_count(self) -> int:
        """Return the number of currently running subagents."""
        return len(self._running_tasks)

    def get_running_count_by_session(self, session_key: str) -> int:
        """Return the number of currently running subagents for a session."""
        tids = self._session_tasks.get(session_key, set())
        return sum(
            1 for tid in tids
            if tid in self._running_tasks and not self._running_tasks[tid].done()
        )

    def get_running_statuses_by_session(self, session_key: str) -> list[SubagentStatus]:
        """Return *SubagentStatus* for every running subagent in *session_key*."""
        tids = self._session_tasks.get(session_key, set())
        return [
            self._task_statuses[tid]
            for tid in tids
            if tid in self._running_tasks
            and not self._running_tasks[tid].done()
            and tid in self._task_statuses
        ]

    def get_status_snapshots(
        self,
        *,
        session_key: str | None = None,
        task_id: str | None = None,
        include_completed: bool = True,
    ) -> list[dict[str, Any]]:
        """Return structured status snapshots for orchestration tools.

        ``_session_tasks`` only tracks currently running tasks.  Completed
        statuses are intentionally retained in ``_task_statuses`` for a short
        window, so session filtering also consults ``SubagentStatus.session_key``.
        """
        snapshots: list[dict[str, Any]] = []
        for tid, status in self._task_statuses.items():
            if task_id and tid != task_id:
                continue
            if session_key and not self._status_belongs_to_session(tid, status, session_key):
                continue
            state = self._status_state(tid, status)
            if not include_completed and state != "running":
                continue
            snapshots.append(self._status_snapshot(tid, status, state))
        snapshots.sort(key=lambda s: (s["state"] != "running", s["started_at_monotonic"]))
        return snapshots

    async def wait_for_subagents(
        self,
        *,
        session_key: str | None = None,
        task_id: str | None = None,
        timeout_sec: float = 300.0,
        wait_for: str = "any",
    ) -> dict[str, Any]:
        """Wait for running subagents without cancelling them on timeout."""
        selected = self._select_running_tasks(session_key=session_key, task_id=task_id)
        if task_id and task_id not in self._task_statuses:
            return {
                "status": "unknown_task",
                "task_id": task_id,
                "message": f"No subagent found with task_id={task_id}.",
                "subagents": [],
            }
        if not selected:
            return {
                "status": "no_running_subagents",
                "message": "No running subagents match the requested scope.",
                "subagents": self.get_status_snapshots(
                    session_key=session_key,
                    task_id=task_id,
                    include_completed=True,
                ),
            }

        tasks = [task for _, task in selected]
        timeout = max(0.0, float(timeout_sec))
        return_when = (
            asyncio.ALL_COMPLETED if wait_for == "all" else asyncio.FIRST_COMPLETED
        )
        done, pending = await asyncio.wait(
            tasks,
            timeout=timeout,
            return_when=return_when,
        )
        snapshots = self.get_status_snapshots(
            session_key=session_key,
            task_id=task_id,
            include_completed=True,
        )
        if done and (wait_for != "all" or not pending):
            done_tids = {tid for tid, task in selected if task in done}
            done_states = {
                snap.get("state")
                for snap in snapshots
                if snap.get("task_id") in done_tids
            }
            if "interrupted" in done_states:
                status = "interrupted"
            elif "error" in done_states:
                status = "error"
            else:
                status = "completed"
        else:
            status = "timeout"
        return {
            "status": status,
            "wait_for": wait_for,
            "timeout_sec": timeout,
            "completed_count": len(done),
            "running_count": len(pending),
            "subagents": snapshots,
        }

    def _select_running_tasks(
        self,
        *,
        session_key: str | None,
        task_id: str | None,
    ) -> list[tuple[str, asyncio.Task[None]]]:
        selected: list[tuple[str, asyncio.Task[None]]] = []
        for tid, task in self._running_tasks.items():
            if task.done():
                continue
            status = self._task_statuses.get(tid)
            if status is None:
                continue
            if task_id and tid != task_id:
                continue
            if session_key and not self._status_belongs_to_session(tid, status, session_key):
                continue
            selected.append((tid, task))
        return selected

    def _status_belongs_to_session(
        self,
        task_id: str,
        status: SubagentStatus,
        session_key: str,
    ) -> bool:
        if status.session_key == session_key:
            return True
        return task_id in self._session_tasks.get(session_key, set())

    def _status_state(self, task_id: str, status: SubagentStatus) -> str:
        task = self._running_tasks.get(task_id)
        if task is not None and not task.done():
            return "running"
        if task is not None and task.cancelled():
            return "cancelled"
        if status.phase == "error" or status.stop_reason in {"error", "tool_error"}:
            return "error"
        if status.stop_reason in {"max_iterations", "context_exhausted"}:
            return "interrupted"
        if status.phase == "done":
            return "completed"
        return "unknown"

    def _status_snapshot(
        self,
        task_id: str,
        status: SubagentStatus,
        state: str,
    ) -> dict[str, Any]:
        elapsed_sec = max(0.0, time.monotonic() - status.started_at)
        heartbeat_age_sec = max(0.0, time.time() - status.last_heartbeat_at)
        return {
            "task_id": task_id,
            "agent_name": status.agent_name,
            "label": status.label,
            "state": state,
            "phase": status.phase,
            "iteration": status.iteration,
            "stop_reason": status.stop_reason,
            "error": status.error,
            "elapsed_sec": round(elapsed_sec, 3),
            "last_heartbeat_age_sec": round(heartbeat_age_sec, 3),
            "last_heartbeat_at": status.last_heartbeat_at,
            "started_at_monotonic": status.started_at,
            "session_key": status.session_key,
            "task_description": status.task_description,
            "tool_events": list(status.tool_events[-5:]),
            "usage": dict(status.usage),
        }

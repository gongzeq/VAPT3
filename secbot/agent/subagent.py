"""Subagent manager for background task execution."""

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

from secbot.agent.blackboard import Blackboard, BlackboardRegistry
from secbot.agent.hook import AgentHook, AgentHookContext
from secbot.agent.runner import AgentRunner, AgentRunSpec
from secbot.agent.skills import BUILTIN_SKILLS_DIR
from secbot.agent.tools.ask import AskUserTool
from secbot.agent.tools.blackboard import BlackboardReadTool, BlackboardWriteTool
from secbot.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from secbot.agent.tools.registry import ToolRegistry
from secbot.agent.tools.search import GlobTool, GrepTool
from secbot.agent.tools.shell import ExecTool
from secbot.agent.tools.skill import bind_skill_context, current_skill_confirm, discover_skill_tools
from secbot.agent.tools.web import WebFetchTool, WebSearchTool
from secbot.bus.events import InboundMessage
from secbot.bus.queue import MessageBus
from secbot.config.schema import AgentDefaults, ExecToolConfig, WebToolsConfig
from secbot.providers.base import LLMProvider
from secbot.utils.prompt_templates import render_template

if TYPE_CHECKING:
    from secbot.agents.registry import AgentRegistry, ExpertAgentSpec


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
    # Wall-clock timestamp (epoch seconds) of the last heartbeat — refreshed
    # on every checkpoint and lifecycle transition. Surfaced over
    # ``GET /api/agents?include_status=true`` and the ``agent_status`` event.
    last_heartbeat_at: float = field(default_factory=time.time)
    # Resolved expert-agent registry name when ``spawn(agent=...)`` was used.
    # Empty for ad-hoc subagents. ``/api/agents?include_status=true`` keys
    # status off this field so the runtime row matches a registry row.
    agent_name: str = ""


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
        # PR3: optional expert-agent registry. When present, ``spawn(agent=...)``
        # resolves the named spec and ``_run_subagent`` filters the skill tool
        # set down to ``spec.scoped_skills``.
        self.agent_registry: "AgentRegistry | None" = agent_registry
        self._running_tasks: dict[str, asyncio.Task[None]] = {}
        self._task_statuses: dict[str, SubagentStatus] = {}
        self._session_tasks: dict[str, set[str]] = {}  # session_key -> {task_id, ...}

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
    ) -> str:
        """Spawn a subagent to execute a task in the background."""
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

        status = SubagentStatus(
            task_id=task_id,
            label=display_label,
            task_description=task,
            started_at=time.monotonic(),
            agent_name=(agent or ""),
        )
        self._task_statuses[task_id] = status

        bg_task = asyncio.create_task(
            self._run_subagent(task_id, task, display_label, origin, status, origin_message_id, spec)
        )
        self._running_tasks[task_id] = bg_task
        if session_key:
            self._session_tasks.setdefault(session_key, set()).add(task_id)

        def _cleanup(_: asyncio.Task) -> None:
            self._running_tasks.pop(task_id, None)
            self._task_statuses.pop(task_id, None)
            if session_key and (ids := self._session_tasks.get(session_key)):
                ids.discard(task_id)
                if not ids:
                    del self._session_tasks[session_key]

        bg_task.add_done_callback(_cleanup)

        logger.info("Spawned subagent [{}]: {}", task_id, display_label)
        await self._broadcast_agent_event(
            origin={"channel": origin_channel, "chat_id": origin_chat_id},
            type="subagent_spawned",
            payload={
                "task_id": task_id,
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

        try:
            # Build subagent tools (no message tool, no spawn tool)
            tools = ToolRegistry()
            allowed_dir = self.workspace if (self.restrict_to_workspace or self.exec_config.sandbox) else None
            extra_read = [BUILTIN_SKILLS_DIR] if allowed_dir else None
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
            tools.register(BlackboardWriteTool(blackboard=resolved_blackboard, agent_name=label))
            tools.register(BlackboardReadTool(blackboard=resolved_blackboard))
            if self.exec_config.enable:
                tools.register(ExecTool(
                    working_dir=str(self.workspace),
                    timeout=self.exec_config.timeout,
                    restrict_to_workspace=self.restrict_to_workspace,
                    sandbox=self.exec_config.sandbox,
                    path_append=self.exec_config.path_append,
                    allowed_env_keys=self.exec_config.allowed_env_keys,
                    allow_patterns=self.exec_config.allow_patterns,
                    deny_patterns=self.exec_config.deny_patterns,
                ))
            if self.web_config.enable:
                tools.register(
                    WebSearchTool(
                        config=self.web_config.search,
                        proxy=self.web_config.proxy,
                        user_agent=self.web_config.user_agent,
                    )
                )
                tools.register(
                    WebFetchTool(
                        config=self.web_config.fetch,
                        proxy=self.web_config.proxy,
                        user_agent=self.web_config.user_agent,
                    )
                )
            # Subagents also get SkillTool instances so they can run nmap /
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
            bind_skill_context(
                scan_id=task_id,
                scan_dir=self.workspace / ".secbot" / "scans" / task_id,
                confirm=parent_confirm,
            )
            system_prompt = self._build_subagent_prompt(spec=spec)
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

            result = await self.runner.run(AgentRunSpec(
                initial_messages=messages,
                tools=tools,
                model=self.model,
                max_iterations=self.max_iterations,
                max_tool_result_chars=self.max_tool_result_chars,
                hook=_SubagentHook(
                    task_id,
                    status,
                    broadcast_fn=_broadcast_tool_event,
                    agent_name=label,
                    critical_tool_names=critical_tool_names,
                ),
                max_iterations_message="Task completed but no final response was generated.",
                error_message=None,
                fail_on_tool_error=True,
                checkpoint_callback=_on_checkpoint,
            ))
            status.phase = "done"
            status.stop_reason = result.stop_reason

            if result.stop_reason == "tool_error":
                status.tool_events = list(result.tool_events)
                await self._announce_result(
                    task_id, label, task,
                    self._format_partial_progress(result),
                    origin, "error", origin_message_id,
                )
                await self._broadcast_agent_status(
                    origin=origin,
                    agent_name=(spec.name if spec is not None else label),
                    status="error",
                    current_task_id=None,
                )
            elif result.stop_reason == "error":
                await self._announce_result(
                    task_id, label, task,
                    result.error or "Error: subagent execution failed.",
                    origin, "error", origin_message_id,
                )
                await self._broadcast_agent_status(
                    origin=origin,
                    agent_name=(spec.name if spec is not None else label),
                    status="error",
                    current_task_id=None,
                )
            else:
                final_result = result.final_content or "Task completed but no final response was generated."
                logger.info("Subagent [{}] completed successfully", task_id)
                await self._announce_result(task_id, label, task, final_result, origin, "ok", origin_message_id)
                await self._broadcast_agent_status(
                    origin=origin,
                    agent_name=(spec.name if spec is not None else label),
                    status="idle",
                    current_task_id=None,
                )

        except Exception as e:
            status.phase = "error"
            status.error = str(e)
            logger.exception("Subagent [{}] failed", task_id)
            await self._announce_result(task_id, label, task, f"Error: {e}", origin, "error", origin_message_id)
            await self._broadcast_agent_status(
                origin=origin,
                agent_name=(spec.name if spec is not None else label),
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
    ) -> None:
        """Announce the subagent result to the main agent via the message bus."""
        status_text = "completed successfully" if status == "ok" else "failed"

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
            sender_id="subagent",
            chat_id=f"{origin['channel']}:{origin['chat_id']}",
            content=announce_content,
            session_key_override=override,
            metadata=metadata,
        )

        await self.bus.publish_inbound(msg)
        await self._broadcast_agent_event(
            origin=origin,
            type="subagent_done",
            payload={
                "task_id": task_id,
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
        self,
        *,
        spec: "ExpertAgentSpec | None" = None,
    ) -> str:
        """Build a focused system prompt for the subagent.

        When ``spec`` is provided, the expert-agent's ``system_prompt`` is
        prepended so the subagent adopts that role before the generic secbot
        subagent instructions.
        """
        from secbot.agent.context import ContextBuilder
        from secbot.agent.skills import SkillsLoader

        time_ctx = ContextBuilder._build_runtime_context(None, None)
        skills_summary = SkillsLoader(
            self.workspace,
            disabled_skills=self.disabled_skills,
        ).build_skills_summary()
        base = render_template(
            "agent/subagent_system.md",
            time_ctx=time_ctx,
            workspace=str(self.workspace),
            skills_summary=skills_summary or "",
        )
        if spec is None:
            return base
        return f"{spec.system_prompt.rstrip()}\n\n{base}"

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

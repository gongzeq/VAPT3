"""Subagent manager for background task execution."""

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from secbot.agent.hook import AgentHook, AgentHookContext
from secbot.agent.runner import AgentRunner, AgentRunSpec
from secbot.agent.skills import BUILTIN_SKILLS_DIR
from secbot.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from secbot.agent.tools.registry import ToolRegistry
from secbot.agent.tools.search import GlobTool, GrepTool
from secbot.agent.tools.shell import ExecTool
from secbot.agent.tools.skill import bind_skill_context, discover_skill_tools
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


class _SubagentHook(AgentHook):
    """Hook for subagent execution — logs tool calls and updates status."""

    def __init__(self, task_id: str, status: SubagentStatus | None = None) -> None:
        super().__init__()
        self._task_id = task_id
        self._status = status

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        for tool_call in context.tool_calls:
            args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
            logger.debug(
                "Subagent [{}] executing: {} with arguments: {}",
                self._task_id, tool_call.name, args_str,
            )

    async def after_iteration(self, context: AgentHookContext) -> None:
        if self._status is None:
            return
        self._status.iteration = context.iteration
        self._status.tool_events = list(context.tool_events)
        self._status.usage = dict(context.usage)
        if context.error:
            self._status.error = str(context.error)


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

        async def _on_checkpoint(payload: dict) -> None:
            status.phase = payload.get("phase", status.phase)
            status.iteration = payload.get("iteration", status.iteration)
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
            for skill_tool in discover_skill_tools(
                BUILTIN_SKILLS_DIR,
                workspace=self.workspace,
            ):
                if scoped is not None and skill_tool.name not in scoped:
                    continue
                tools.register(skill_tool)
            # Inherit the parent loop's per-turn SkillContext binding so raw
            # logs and scan_id stay consistent across parent + children.
            bind_skill_context(
                scan_id=task_id,
                scan_dir=self.workspace / ".secbot" / "scans" / task_id,
            )
            system_prompt = self._build_subagent_prompt(spec=spec)
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task},
            ]

            result = await self.runner.run(AgentRunSpec(
                initial_messages=messages,
                tools=tools,
                model=self.model,
                max_iterations=self.max_iterations,
                max_tool_result_chars=self.max_tool_result_chars,
                hook=_SubagentHook(task_id, status),
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
            elif result.stop_reason == "error":
                await self._announce_result(
                    task_id, label, task,
                    result.error or "Error: subagent execution failed.",
                    origin, "error", origin_message_id,
                )
            else:
                final_result = result.final_content or "Task completed but no final response was generated."
                logger.info("Subagent [{}] completed successfully", task_id)
                await self._announce_result(task_id, label, task, final_result, origin, "ok", origin_message_id)

        except Exception as e:
            status.phase = "error"
            status.error = str(e)
            logger.exception("Subagent [{}] failed", task_id)
            await self._announce_result(task_id, label, task, f"Error: {e}", origin, "error", origin_message_id)

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

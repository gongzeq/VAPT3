"""Subagent lifecycle inspection tools for the orchestrator."""

from __future__ import annotations

import json
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from secbot.agent.tools.base import Tool, tool_parameters
from secbot.agent.tools.schema import (
    BooleanSchema,
    IntegerSchema,
    StringSchema,
    tool_parameters_schema,
)

if TYPE_CHECKING:
    from secbot.agent.subagent import SubagentManager


class _SubagentSessionContext:
    """Shared context plumbing for session-scoped subagent tools."""

    def __init__(self) -> None:
        self._origin_channel: ContextVar[str] = ContextVar(
            f"{self.__class__.__name__}_origin_channel",
            default="cli",
        )
        self._origin_chat_id: ContextVar[str] = ContextVar(
            f"{self.__class__.__name__}_origin_chat_id",
            default="direct",
        )
        self._session_key: ContextVar[str] = ContextVar(
            f"{self.__class__.__name__}_session_key",
            default="cli:direct",
        )

    def set_context(
        self,
        channel: str,
        chat_id: str,
        effective_key: str | None = None,
    ) -> None:
        self._origin_channel.set(channel)
        self._origin_chat_id.set(chat_id)
        self._session_key.set(effective_key or f"{channel}:{chat_id}")

    def _current_session_key(self) -> str:
        return self._session_key.get()


@tool_parameters(
    tool_parameters_schema(
        task_id=StringSchema(
            "Optional subagent task id. Omit to list subagents for the current session.",
            nullable=True,
        ),
        include_completed=BooleanSchema(
            description=(
                "Include recently completed/error/interrupted subagents retained "
                "by the runtime. Defaults to true."
            ),
            default=True,
        ),
    )
)
class CheckSubagentsTool(_SubagentSessionContext, Tool):
    """Return the current session's subagent lifecycle snapshot."""

    def __init__(self, manager: "SubagentManager") -> None:
        _SubagentSessionContext.__init__(self)
        self._manager = manager

    @property
    def name(self) -> str:
        return "check_subagents"

    @property
    def description(self) -> str:
        return (
            "Check spawned subagents for the current session. Use this to see "
            "which subagents are running, completed, interrupted, or errored. "
            "Do not poll read_assets to infer subagent lifecycle."
        )

    @property
    def read_only(self) -> bool:
        return True

    async def execute(
        self,
        task_id: str | None = None,
        include_completed: bool = True,
        **kwargs: Any,
    ) -> str:
        normalized_task_id = task_id.strip() if isinstance(task_id, str) and task_id.strip() else None
        snapshots = self._manager.get_status_snapshots(
            session_key=self._current_session_key(),
            task_id=normalized_task_id,
            include_completed=bool(include_completed),
        )
        payload = {
            "session_key": self._current_session_key(),
            "running_count": sum(1 for s in snapshots if s.get("state") == "running"),
            "subagents": snapshots,
        }
        if normalized_task_id and not snapshots:
            payload["status"] = "unknown_task"
            payload["message"] = f"No subagent found with task_id={normalized_task_id}."
        else:
            payload["status"] = "ok"
        return json.dumps(payload, ensure_ascii=False)


@tool_parameters(
    tool_parameters_schema(
        task_id=StringSchema(
            "Optional subagent task id. Omit to wait on running subagents in the current session.",
            nullable=True,
        ),
        wait_for=StringSchema(
            "Whether to wait for any matching subagent or all matching subagents.",
            enum=("any", "all"),
            nullable=True,
        ),
        timeout_sec=IntegerSchema(
            description=(
                "Maximum time to wait. Must be 1..300 seconds. Defaults to 300."
            ),
            minimum=1,
            maximum=300,
            nullable=True,
        ),
    )
)
class WaitSubagentTool(_SubagentSessionContext, Tool):
    """Block until a subagent reaches a terminal state or timeout expires."""

    def __init__(self, manager: "SubagentManager") -> None:
        _SubagentSessionContext.__init__(self)
        self._manager = manager

    @property
    def name(self) -> str:
        return "wait_subagent"

    @property
    def description(self) -> str:
        return (
            "Wait for a spawned subagent to finish. Use this when orchestration "
            "needs a subagent_result before deciding the next stage. On timeout, "
            "do not retry blindly; call check_subagents, then replan or ask the user."
        )

    @property
    def read_only(self) -> bool:
        return True

    @property
    def exclusive(self) -> bool:
        return True

    async def execute(
        self,
        task_id: str | None = None,
        wait_for: str | None = None,
        timeout_sec: int | None = None,
        **kwargs: Any,
    ) -> str:
        normalized_task_id = task_id.strip() if isinstance(task_id, str) and task_id.strip() else None
        normalized_wait_for = wait_for if wait_for in {"any", "all"} else "any"
        timeout = 300 if timeout_sec is None else max(1, min(int(timeout_sec), 300))
        result = await self._manager.wait_for_subagents(
            session_key=self._current_session_key(),
            task_id=normalized_task_id,
            timeout_sec=timeout,
            wait_for=normalized_wait_for,
        )
        result["session_key"] = self._current_session_key()
        return json.dumps(result, ensure_ascii=False)

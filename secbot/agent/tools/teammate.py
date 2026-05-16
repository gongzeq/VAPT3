"""Tools for persistent teammate management and mailboxes."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from secbot.agent.tools.base import Tool
from secbot.agent.tools.schema import StringSchema, tool_parameters_schema

if TYPE_CHECKING:
    from secbot.agent.teammate import TeammateManager


def _format_error(exc: Exception) -> str:
    if isinstance(exc, KeyError) and exc.args:
        return f"Error: {exc.args[0]}"
    return f"Error: {exc}"


class SpawnTeammateTool(Tool):
    """Create a persistent teammate or assign new work to an idle teammate."""

    def __init__(self, manager: TeammateManager) -> None:
        self._manager = manager

    @property
    def name(self) -> str:
        return "spawn_teammate"

    @property
    def description(self) -> str:
        return (
            "Create a persistent teammate with a durable identity and assign it "
            "work. Reusing the same name assigns new work to that idle teammate. "
            "Use this only when the teammate needs mailbox-based communication "
            "across turns; for one-shot expert work use delegate_task."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return tool_parameters_schema(
            name=StringSchema("Stable teammate name, e.g. alice or port-reviewer"),
            role=StringSchema("Short role description for this teammate"),
            task=StringSchema("Concrete work assignment for the teammate"),
            required=["name", "role", "task"],
        )

    async def execute(self, **kwargs: Any) -> str:
        try:
            record = await self._manager.spawn(
                name=str(kwargs.get("name", "")),
                role=str(kwargs.get("role", "")),
                task=str(kwargs.get("task", "")),
            )
        except (KeyError, RuntimeError, ValueError) as exc:
            return _format_error(exc)
        return (
            f"Teammate `{record.name}` is {record.status}; "
            f"role={record.role}; task={record.current_task or '<none>'}."
        )


class ListTeammatesTool(Tool):
    """List the durable teammate roster."""

    def __init__(self, manager: TeammateManager) -> None:
        self._manager = manager

    @property
    def name(self) -> str:
        return "list_teammates"

    @property
    def description(self) -> str:
        return "List persistent teammates and their lifecycle status."

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> str:
        records = await self._manager.list_teammates()
        if not records:
            return "No persistent teammates."
        return json.dumps([record.to_dict() for record in records], ensure_ascii=False, indent=2)


class SendTeammateMessageTool(Tool):
    """Append a structured message to a teammate inbox."""

    def __init__(self, manager: TeammateManager, *, sender: str = "orchestrator") -> None:
        self._manager = manager
        self._sender = sender

    @property
    def name(self) -> str:
        return "send_teammate_message"

    @property
    def description(self) -> str:
        return (
            "Append one structured JSONL message to another teammate's inbox. "
            "The recipient reads and clears it with read_teammate_inbox."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return tool_parameters_schema(
            to=StringSchema("Recipient teammate name, or orchestrator"),
            content=StringSchema("Message body to append"),
            msg_type=StringSchema(
                "Message type label",
                enum=("message", "status", "request", "response", "broadcast"),
            ),
            required=["to", "content"],
        )

    async def execute(self, **kwargs: Any) -> str:
        try:
            message = await self._manager.send(
                sender=self._sender,
                to=str(kwargs.get("to", "")),
                content=str(kwargs.get("content", "")),
                msg_type=str(kwargs.get("msg_type") or "message"),
            )
        except (KeyError, ValueError) as exc:
            return _format_error(exc)
        return f"Message sent to `{message['to']}` ({message['type']})."


class ReadTeammateInboxTool(Tool):
    """Drain a teammate inbox."""

    def __init__(
        self,
        manager: TeammateManager,
        *,
        default_name: str = "orchestrator",
        allow_name_override: bool = True,
    ) -> None:
        self._manager = manager
        self._default_name = default_name
        self._allow_name_override = allow_name_override

    @property
    def name(self) -> str:
        return "read_teammate_inbox"

    @property
    def description(self) -> str:
        return (
            "Read and clear a teammate inbox. This is drain-on-read: returned "
            "messages are removed from the JSONL mailbox."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return tool_parameters_schema(
            name=StringSchema(
                "Inbox owner to drain. Omit to read the current actor's inbox.",
                nullable=True,
            ),
        )

    async def execute(self, **kwargs: Any) -> str:
        requested = kwargs.get("name") or self._default_name
        if not self._allow_name_override and requested != self._default_name:
            return "Error: teammates may only read their own inbox."
        try:
            messages = await self._manager.read_inbox(str(requested))
        except ValueError as exc:
            return _format_error(exc)
        if not messages:
            return "Inbox is empty."
        return json.dumps(messages, ensure_ascii=False, indent=2)


class ShutdownTeammateTool(Tool):
    """Mark a teammate as shutdown."""

    def __init__(self, manager: TeammateManager) -> None:
        self._manager = manager

    @property
    def name(self) -> str:
        return "shutdown_teammate"

    @property
    def description(self) -> str:
        return (
            "Mark an idle persistent teammate as shutdown. This prevents future "
            "work assignments; the MVP does not force-cancel an already running "
            "teammate thread."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return tool_parameters_schema(
            name=StringSchema("Teammate name to shutdown"),
            required=["name"],
        )

    async def execute(self, **kwargs: Any) -> str:
        try:
            record = await self._manager.shutdown(str(kwargs.get("name", "")))
        except (KeyError, ValueError) as exc:
            return _format_error(exc)
        return f"Teammate `{record.name}` is {record.status}."

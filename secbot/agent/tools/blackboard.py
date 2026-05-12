"""Blackboard read/write tools for sub-agents."""

from __future__ import annotations

from typing import Any

from secbot.agent.blackboard import Blackboard
from secbot.agent.tools.base import Tool


class BlackboardWriteTool(Tool):
    """Write a discovery/finding to the shared blackboard."""

    def __init__(self, blackboard: Blackboard, agent_name: str = "unknown") -> None:
        self._blackboard = blackboard
        self._agent_name = agent_name

    @property
    def name(self) -> str:
        return "blackboard_write"

    @property
    def description(self) -> str:
        return (
            "Write an important finding or discovery to the shared blackboard. "
            "Other agents can read your entries. Use this to share key information "
            "that other agents may need."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The finding or discovery text to write to the blackboard.",
                },
            },
            "required": ["text"],
        }

    async def execute(self, **kwargs: Any) -> str:
        text = kwargs.get("text", "")
        if not text.strip():
            return "Error: text cannot be empty."
        entry = await self._blackboard.write(self._agent_name, text.strip())
        return f"Written to blackboard (id={entry.id}): {text.strip()}"


class BlackboardReadTool(Tool):
    """Read all entries from the shared blackboard."""

    def __init__(self, blackboard: Blackboard) -> None:
        self._blackboard = blackboard

    @property
    def name(self) -> str:
        return "read_blackboard"

    @property
    def description(self) -> str:
        return (
            "Read all entries from the shared blackboard. "
            "Shows findings written by all agents in this orchestration task."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
        }

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> str:
        entries = await self._blackboard.read_all()
        if not entries:
            return "Blackboard is empty. No entries yet."
        lines = []
        for e in entries:
            lines.append(f"[{e.agent_name}] ({e.id}): {e.text}")
        return "\n".join(lines)

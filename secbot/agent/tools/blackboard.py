"""Blackboard read/write tools for sub-agents."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from secbot.agent.blackboard import Blackboard
from secbot.agent.tools.base import Tool

# Either a concrete Blackboard or a zero-arg callable that returns the
# *currently active* one. The callable form lets ``AgentLoop`` swap in the
# per-chat instance from ``BlackboardRegistry`` on every turn without having
# to re-register tools.
BlackboardSource = Blackboard | Callable[[], Blackboard]


def _resolve(source: BlackboardSource) -> Blackboard:
    return source() if callable(source) else source


class BlackboardWriteTool(Tool):
    """Write a discovery/finding to the shared blackboard."""

    def __init__(self, blackboard: BlackboardSource, agent_name: str = "unknown") -> None:
        self._blackboard = blackboard
        self._agent_name = agent_name

    @property
    def name(self) -> str:
        return "blackboard_write"

    @property
    def description(self) -> str:
        return (
            "Write a concise, free-form note to the shared blackboard so other "
            "agents (and the orchestrator) can see your current task state. "
            "Prefer short natural-language sentences over JSON blobs. You are "
            "strongly encouraged to start the note with ONE of these tags so "
            "readers can triage quickly:\n"
            "  [milestone] a task step you just completed\n"
            "  [blocker]   something that stops you from making progress and "
            "needs attention (missing creds, denied approval, unreachable "
            "target, ambiguous scope, ...)\n"
            "  [finding]   a concrete discovery other agents may need (an open "
            "service, a vulnerable endpoint, a credential, ...)\n"
            "  [progress]  an in-flight status update (e.g. '2/12 hosts "
            "scanned')\n"
            "Tags are optional — the blackboard accepts any free text. Keep "
            "each note short (one or two sentences). Do NOT dump raw tool "
            "output here; use your own summary_json for structured results."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": (
                        "Free-form note for the shared blackboard. Keep it "
                        "short. Optionally prefix with [milestone] / "
                        "[blocker] / [finding] / [progress] so other agents "
                        "can triage at a glance."
                    ),
                },
            },
            "required": ["text"],
        }

    async def execute(self, **kwargs: Any) -> str:
        text = kwargs.get("text", "")
        if not text.strip():
            return "Error: text cannot be empty."
        entry = await _resolve(self._blackboard).write(self._agent_name, text.strip())
        return f"Written to blackboard (id={entry.id}): {text.strip()}"


class BlackboardReadTool(Tool):
    """Read all entries from the shared blackboard."""

    def __init__(self, blackboard: BlackboardSource) -> None:
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
        entries = await _resolve(self._blackboard).read_all()
        if not entries:
            return "Blackboard is empty. No entries yet."
        lines = []
        for e in entries:
            lines.append(f"[{e.agent_name}] ({e.id}): {e.text}")
        return "\n".join(lines)

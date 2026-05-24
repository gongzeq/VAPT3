"""Blackboard read/write tools for sub-agents."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from secbot.agent.blackboard import STRUCTURED_KINDS, Blackboard, BlackboardValueError
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

    def __init__(
        self,
        blackboard: BlackboardSource,
        agent_name: str = "unknown",
        *,
        tool_name: str = "blackboard_write",
    ) -> None:
        self._blackboard = blackboard
        self._agent_name = agent_name
        self._tool_name = tool_name

    @property
    def name(self) -> str:
        return self._tool_name

    @property
    def description(self) -> str:
        return (
            "Write a structured blackboard entry or a legacy concise note to the shared "
            "blackboard. The blackboard is now a high-level dashboard for "
            "the orchestrator and the human UI — NOT a per-asset feed. "
            "Prefer typed writes with kind+payload. Legacy text remains supported "
            "for short summaries, optionally prefixed with [milestone], [blocker], "
            "[finding], or [progress].\n\n"
            "DO NOT use the blackboard for individual asset discoveries. "
            "Per-asset entries (each URL, port, service, credential, "
            "vulnerability, tech fingerprint) MUST go to ``asset_push`` "
            "instead, which both records the asset and wakes the "
            "orchestrator in real time. The blackboard is for ONE "
            "summary per phase, not one entry per asset.\n\n"
            "Writing rules:\n"
            "1. Each note MUST be your own one-or-two-sentence summary "
            "or judgement. Do NOT paste raw scanner stdout, full HTTP "
            "responses, or JSON dumps.\n"
            "2. Do NOT repeat what was already on the blackboard.\n"
            "3. Before writing, ask: 'Will this help the orchestrator "
            "or the next agent make a strategic decision?' If not, skip "
            "it (and use ``asset_push`` if it's a concrete asset)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": list(STRUCTURED_KINDS),
                    "description": "Structured entry kind. Required when payload is provided.",
                },
                "payload": {
                    "type": "object",
                    "description": "Structured payload for kind. Required when kind is provided.",
                    "additionalProperties": True,
                },
                "text": {
                    "type": "string",
                    "description": (
                        "Legacy free-form note for the shared blackboard. Keep it "
                        "short. Use this only when a typed kind/payload is not practical."
                    ),
                },
            },
            "anyOf": [
                {"required": ["kind", "payload"]},
                {"required": ["text"]},
            ],
        }

    async def execute(self, **kwargs: Any) -> str:
        board = _resolve(self._blackboard)
        kind = kwargs.get("kind")
        payload = kwargs.get("payload")
        if kind is not None or payload is not None:
            if not isinstance(kind, str) or not kind.strip():
                return "Error: kind is required for structured blackboard writes."
            if not isinstance(payload, dict):
                return "Error: payload must be an object for structured blackboard writes."
            try:
                entry = await board.write(self._agent_name, kind, payload)
            except BlackboardValueError as exc:
                return f"Error: {exc}"
            return f"Written to blackboard (id={entry.id}, kind={entry.kind})."

        text = kwargs.get("text", "")
        if not isinstance(text, str) or not text.strip():
            return "Error: text cannot be empty."
        entry = await board.write_text(self._agent_name, text.strip())
        return f"Written to blackboard (id={entry.id}): {text.strip()}"


class BlackboardReadTool(Tool):
    """Read a compact snapshot from the shared blackboard."""

    def __init__(self, blackboard: BlackboardSource) -> None:
        self._blackboard = blackboard

    @property
    def name(self) -> str:
        return "read_blackboard"

    @property
    def description(self) -> str:
        return (
            "Read a compact structured snapshot from the shared blackboard: "
            "scope, current phase, findings, open hypotheses, approvals, "
            "recent blockers, and recent milestones."
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
        board = _resolve(self._blackboard)
        if len(board) == 0:
            return "Blackboard is empty. No entries yet."
        snapshot = await board.snapshot()
        return snapshot.to_markdown()


class BlackboardReadFullTool(Tool):
    """Read raw blackboard entries, optionally filtered by kind."""

    def __init__(self, blackboard: BlackboardSource) -> None:
        self._blackboard = blackboard

    @property
    def name(self) -> str:
        return "read_blackboard_full"

    @property
    def description(self) -> str:
        return "Read raw blackboard entries. Use only when the compact snapshot omits needed detail."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "kinds": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(STRUCTURED_KINDS)},
                    "description": "Optional kind filter.",
                }
            },
        }

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> str:
        kinds = kwargs.get("kinds")
        board = _resolve(self._blackboard)
        try:
            if kinds:
                entries = await board.read_by_kind(kinds)
            else:
                entries = await board.read_all()
        except BlackboardValueError as exc:
            return f"Error: {exc}"

        if not entries:
            return "Blackboard is empty. No entries yet."

        lines: list[str] = []
        for e in entries:
            payload = e.payload or {}
            text = e.text if e.text is not None else payload
            lines.append(f"[{e.agent_name}] ({e.id}, kind={e.kind}): {text}")
        return "\n".join(lines)

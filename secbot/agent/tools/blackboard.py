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
            "Write a CONCISE AGGREGATE / MILESTONE note to the shared "
            "blackboard. The blackboard is now a high-level dashboard for "
            "the orchestrator and the human UI — NOT a per-asset feed. "
            "Use it for stage summaries, totals, blockers, and milestones. "
            "Recommended tags:\n"
            "  [milestone] a phase you just completed (e.g. 'crawl_web "
            "finished, found 12 URLs / 3 forms / 1 OAuth endpoint')\n"
            "  [blocker]   something stopping progress (missing creds, "
            "denied approval, unreachable target, ambiguous scope)\n"
            "  [progress]  in-flight status (e.g. '2/12 hosts scanned')\n"
            "  [finding]   a strategic, decision-altering insight that "
            "the orchestrator must see (e.g. 'target is a Node.js / "
            "OAuth stack — recommend loading auth-bypass skills')\n\n"
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

"""Task-scoped shared blackboard for inter-agent communication."""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# Recognised entry kinds. ``write()`` auto-extracts one of these from the
# leading ``[tag]`` prefix (whitespace-tolerant). LLMs need NOT pass ``kind``
# explicitly — the registry contract is "free text in, kind out".
KNOWN_KINDS: tuple[str, ...] = ("milestone", "blocker", "finding", "progress")
_KIND_PREFIX_RE = re.compile(
    r"^\s*\[(" + "|".join(KNOWN_KINDS) + r")\]",
    flags=re.IGNORECASE,
)


def _extract_kind(text: str) -> str | None:
    """Return the kind name when ``text`` starts with a known ``[tag]`` prefix.

    Whitespace-tolerant; case-insensitive. Returns ``None`` for unprefixed or
    unknown-prefixed text so the front-end can fall back to its own heuristic.
    """
    if not isinstance(text, str):
        return None
    match = _KIND_PREFIX_RE.match(text)
    if match is None:
        return None
    return match.group(1).lower()


@dataclass(slots=True)
class BlackboardEntry:
    """A single blackboard entry."""
    id: str
    agent_name: str
    text: str
    timestamp: float
    kind: str | None = None

    def to_dict(self) -> dict:
        """Serialize this entry for JSON transport."""
        return {
            "id": self.id,
            "agent_name": self.agent_name,
            "text": self.text,
            "timestamp": self.timestamp,
            "kind": self.kind,
        }


class Blackboard:
    """Thread-safe, chat-scoped shared blackboard.

    Historically per-orchestration-task; PR P0 moved ownership to
    ``BlackboardRegistry`` so HTTP refresh-after-reload (``GET
    /api/blackboard?chat_id=...``) can recover entries that survived the
    AgentLoop turn that wrote them. Each ``Blackboard`` is keyed by chat_id
    inside the registry; the chat_id itself is not stored on the instance to
    keep this class drop-in compatible with legacy per-loop usage.
    """

    def __init__(self, on_write: Callable[[BlackboardEntry], Any] | None = None) -> None:
        self._entries: list[BlackboardEntry] = []
        self._lock = asyncio.Lock()
        self._on_write = on_write  # Write callback for frontend notification

    def set_on_write(self, on_write: Callable[[BlackboardEntry], Any] | None) -> None:
        """Replace the write callback (used to bind/unbind per-turn WebSocket broadcast)."""
        self._on_write = on_write

    async def write(self, agent_name: str, text: str) -> BlackboardEntry:
        """Write a new entry to the blackboard (concurrency-safe)."""
        entry = BlackboardEntry(
            id=str(uuid.uuid4())[:8],
            agent_name=agent_name,
            text=text,
            timestamp=time.time(),
            kind=_extract_kind(text),
        )
        async with self._lock:
            self._entries.append(entry)
        # Notify callback (e.g., push to frontend via WebSocket)
        if self._on_write:
            try:
                result = self._on_write(entry)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                pass  # Don't let callback failure break the write
        return entry

    async def read_all(self) -> list[BlackboardEntry]:
        """Read all entries (returns a copy for safety)."""
        async with self._lock:
            return list(self._entries)

    async def clear(self) -> None:
        """Clear all entries (called at orchestration task end)."""
        async with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)

    async def to_dict_list(self) -> list[dict]:
        """Serialize all entries for JSON transport."""
        async with self._lock:
            return [e.to_dict() for e in self._entries]


class BlackboardRegistry:
    """In-memory ``chat_id → Blackboard`` registry.

    ``AgentLoop`` no longer owns its blackboard directly; instead it asks the
    process-wide registry for the instance keyed by the active ``chat_id`` so
    that a page refresh (``GET /api/blackboard?chat_id=...``) can return all
    entries appended across previous turns.

    Lifecycle policy (PRD D3):
    - ``get_or_create`` on AgentLoop turn start
    - Instances are **retained** when the loop ends (in-memory only — no disk
      persistence; restart wipes everything, which is acceptable for P0).
    - ``drop`` is exposed for tests / explicit chat deletion.
    """

    def __init__(self) -> None:
        self._boards: dict[str, Blackboard] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(self, chat_id: str) -> Blackboard:
        """Return the Blackboard for ``chat_id``, creating it on first use."""
        async with self._lock:
            board = self._boards.get(chat_id)
            if board is None:
                board = Blackboard()
                self._boards[chat_id] = board
            return board

    async def get(self, chat_id: str) -> Blackboard | None:
        """Return the Blackboard for ``chat_id`` or ``None`` when absent."""
        async with self._lock:
            return self._boards.get(chat_id)

    async def drop(self, chat_id: str) -> None:
        """Forget the Blackboard for ``chat_id`` (best-effort)."""
        async with self._lock:
            self._boards.pop(chat_id, None)

    def chat_ids(self) -> list[str]:
        """Snapshot of currently-tracked chat ids (lock-free; for diagnostics)."""
        return list(self._boards.keys())

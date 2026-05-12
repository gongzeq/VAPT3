"""Task-scoped shared blackboard for inter-agent communication."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class BlackboardEntry:
    """A single blackboard entry."""
    id: str
    agent_name: str
    text: str
    timestamp: float

    def to_dict(self) -> dict:
        """Serialize this entry for JSON transport."""
        return {
            "id": self.id,
            "agent_name": self.agent_name,
            "text": self.text,
            "timestamp": self.timestamp,
        }


class Blackboard:
    """Thread-safe, task-scoped shared blackboard.

    Lifecycle: created at orchestration task start, destroyed on completion.
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
            return [
                {"id": e.id, "agent_name": e.agent_name, "text": e.text, "timestamp": e.timestamp}
                for e in self._entries
            ]

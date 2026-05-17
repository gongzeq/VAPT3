"""Per-chat in-memory asset feed for inter-agent real-time collaboration.

The "blackboard" stores aggregated, summary-level entries for human
dashboards and high-level orchestrator awareness. The asset feed, in
contrast, captures **every individual asset discovery** (URL, port,
service, credential, vulnerability, technology fingerprint) that
sub-agents append while they run, so the orchestrator can pull the
latest deltas via a cursor and dispatch follow-up work without waiting
for any single sub-agent to terminate.

Storage is **in-memory and per chat_id only** (`AssetFeedRegistry`).
There is **no persistence** — process restart wipes everything, which
is acceptable since the feed is a short-lived collaboration channel,
not a system of record. Persistence belongs to the CMDB, not here.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# Recognised asset kinds. The list is open — sub-agents may push
# additional kinds — but these are the canonical ones documented in
# the tool description so consumers know what to expect.
KNOWN_ASSET_KINDS: tuple[str, ...] = (
    "url",
    "port",
    "service",
    "credential",
    "vuln",
    "tech",
)


@dataclass(slots=True)
class AssetEntry:
    """A single asset feed entry."""

    id: int
    kind: str
    agent_name: str
    payload: dict[str, Any]
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "agent_name": self.agent_name,
            "payload": self.payload,
            "created_at": self.created_at,
        }


class AssetFeed:
    """Append-only in-memory asset list scoped to a single chat.

    Concurrency: protected by an asyncio lock so that multiple
    sub-agents writing simultaneously cannot interleave id assignment.
    """

    def __init__(self) -> None:
        self._entries: list[AssetEntry] = []
        self._next_id: int = 1
        self._lock = asyncio.Lock()
        self._on_append: Callable[[AssetEntry], Any] | None = None

    def set_on_append(
        self, on_append: Callable[[AssetEntry], Any] | None
    ) -> None:
        """Replace the append callback used by loop.py to bind/unbind a
        per-turn WebSocket broadcast. Mirrors
        :meth:`secbot.agent.blackboard.Blackboard.set_on_write`.
        """
        self._on_append = on_append

    async def append(
        self,
        *,
        kind: str,
        agent_name: str,
        payload: dict[str, Any],
    ) -> AssetEntry:
        """Append a new asset entry and return it (id auto-assigned)."""
        async with self._lock:
            entry = AssetEntry(
                id=self._next_id,
                kind=kind,
                agent_name=agent_name,
                payload=dict(payload),
                created_at=time.time(),
            )
            self._next_id += 1
            self._entries.append(entry)
        # Fire append callback outside the lock so a slow broadcaster
        # cannot block other writers. Best-effort: never propagate.
        if self._on_append is not None:
            try:
                result = self._on_append(entry)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                pass
        return entry

    async def since(
        self,
        since_id: int | None = None,
        kind: str | None = None,
        limit: int = 200,
    ) -> list[AssetEntry]:
        """Return entries with ``id > since_id`` (optional kind filter).

        ``limit`` caps the slice size so a single tool invocation cannot
        flood the LLM context with thousands of entries.
        """
        cutoff = since_id or 0
        async with self._lock:
            result = [
                e for e in self._entries
                if e.id > cutoff and (kind is None or e.kind == kind)
            ]
        return result[:limit]

    async def group_by_kind(self) -> dict[str, list[AssetEntry]]:
        async with self._lock:
            grouped: dict[str, list[AssetEntry]] = {}
            for e in self._entries:
                grouped.setdefault(e.kind, []).append(e)
            return grouped

    async def counts_by_kind(self) -> dict[str, int]:
        async with self._lock:
            counts: dict[str, int] = {}
            for e in self._entries:
                counts[e.kind] = counts.get(e.kind, 0) + 1
            return counts

    async def to_dict_list(self) -> list[dict[str, Any]]:
        async with self._lock:
            return [e.to_dict() for e in self._entries]

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def latest_id(self) -> int:
        return self._next_id - 1


@dataclass(slots=True)
class _RegistryState:
    feeds: dict[str, AssetFeed] = field(default_factory=dict)


class AssetFeedRegistry:
    """In-memory ``chat_id → AssetFeed`` registry.

    Mirrors :class:`secbot.agent.blackboard.BlackboardRegistry` so the
    same lifecycle (per-chat creation, in-memory only, ``drop`` on
    explicit deletion) applies.
    """

    def __init__(self) -> None:
        self._feeds: dict[str, AssetFeed] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(self, chat_id: str) -> AssetFeed:
        async with self._lock:
            feed = self._feeds.get(chat_id)
            if feed is None:
                feed = AssetFeed()
                self._feeds[chat_id] = feed
            return feed

    async def get(self, chat_id: str) -> AssetFeed | None:
        async with self._lock:
            return self._feeds.get(chat_id)

    async def drop(self, chat_id: str) -> None:
        async with self._lock:
            self._feeds.pop(chat_id, None)

    def chat_ids(self) -> list[str]:
        return list(self._feeds.keys())

"""Asset feed read/write tools for sub-agents.

The asset feed is the inter-agent communication channel for **discrete
asset discoveries** (URL / port / service / credential / vuln / tech).
``asset_push`` writes one entry per discovery and wakes the orchestrator
via the message bus; ``read_assets`` reads with cursor-based pagination.
See :mod:`secbot.agent.asset_feed` for the underlying registry.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from secbot.agent.asset_feed import KNOWN_ASSET_KINDS, AssetFeed
from secbot.agent.tools.base import Tool
from secbot.bus.events import InboundMessage
from secbot.bus.queue import MessageBus

AssetFeedSource = AssetFeed | Callable[[], AssetFeed]


def _resolve(source: AssetFeedSource) -> AssetFeed:
    return source() if callable(source) else source


class AssetPushTool(Tool):
    """Append a single discrete asset to the chat-scoped asset feed.

    Wakes the orchestrator by publishing a system ``InboundMessage`` with
    ``metadata.injected_event = "asset_discovered"`` so the orchestrator
    can decide whether to dispatch a follow-up agent (e.g. forward a new
    URL/port to ``vuln_detec`` / ``vuln_scan``).
    """

    def __init__(
        self,
        feed: AssetFeedSource,
        *,
        bus: MessageBus | None = None,
        origin: dict[str, str] | Callable[[], dict[str, str] | None] | None = None,
        agent_name: str = "unknown",
    ) -> None:
        self._feed = feed
        self._bus = bus
        self._origin = origin
        self._agent_name = agent_name

    @property
    def name(self) -> str:
        return "asset_push"

    @property
    def description(self) -> str:
        return (
            "Append ONE concrete asset discovery to the shared asset feed "
            "so the orchestrator and other agents can act on it in real "
            "time. Call this once per asset (URL, open port, credential, "
            "vulnerability, technology fingerprint). The orchestrator is "
            "woken up after every push.\n\n"
            "Recognised kinds (use lowercase):\n"
            "  url        — a discovered URL/path/endpoint\n"
            "  port       — an open port (host + port + optional service)\n"
            "  service    — a fingerprinted service / version / banner\n"
            "  credential — a leaked/discovered credential pair\n"
            "  vuln       — a confirmed vulnerability with evidence\n"
            "  tech       — a detected tech stack signal "
            "(framework / CMS / language / OAuth / file-upload point)\n\n"
            "Payload should be a small JSON object capturing only the "
            "decision-relevant fields (e.g. {\"url\": \"https://x/y\", "
            "\"status\": 200, \"title\": \"Login\"}). Do NOT dump raw "
            "scanner stdout. One push per asset — do not batch a list of "
            "assets into one call. Aggregate counts / progress summaries "
            "go to ``blackboard_write``, not here."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "description": (
                        "Asset kind. Recommended: url / port / service / "
                        "credential / vuln / tech."
                    ),
                },
                "payload": {
                    "type": "object",
                    "description": (
                        "Small JSON object with the asset fields. Keep it "
                        "concise; only decision-relevant fields."
                    ),
                },
            },
            "required": ["kind", "payload"],
        }

    async def execute(self, **kwargs: Any) -> str:
        kind = str(kwargs.get("kind", "")).strip().lower()
        payload = kwargs.get("payload")
        if not kind:
            return "Error: kind cannot be empty."
        if not isinstance(payload, dict):
            return "Error: payload must be a JSON object."

        feed = _resolve(self._feed)
        entry = await feed.append(
            kind=kind,
            agent_name=self._agent_name,
            payload=payload,
        )

        # Best-effort orchestrator wake-up. When ``bus`` / ``origin`` are
        # not wired (e.g. unit tests with a bare feed), skip silently —
        # the entry is still persisted and ``read_assets`` works.
        await self._notify_bus(entry_id=entry.id, kind=kind)

        kinds_hint = (
            "" if kind in KNOWN_ASSET_KINDS
            else f" (note: kind '{kind}' is non-standard)"
        )
        return f"asset pushed (id={entry.id}, kind={kind}){kinds_hint}"

    async def _notify_bus(self, *, entry_id: int, kind: str) -> None:
        if self._bus is None or self._origin is None:
            return
        origin = self._origin() if callable(self._origin) else self._origin
        if not origin:
            return
        channel = origin.get("channel")
        chat_id = origin.get("chat_id")
        if not channel or not chat_id:
            return
        session_key = origin.get("session_key") or f"{channel}:{chat_id}"
        try:
            await self._bus.publish_inbound(
                InboundMessage(
                    channel="system",
                    sender_id=self._agent_name,
                    chat_id=f"{channel}:{chat_id}",
                    content=(
                        f"New asset discovered (kind={kind}, id={entry_id}). "
                        "Call read_assets to consume and decide if a "
                        "downstream agent should be dispatched."
                    ),
                    session_key_override=session_key,
                    metadata={
                        "injected_event": "asset_discovered",
                        "asset_id": entry_id,
                        "asset_kind": kind,
                        "asset_agent": self._agent_name,
                    },
                )
            )
        except Exception:
            # Wake-up is best-effort. The asset is already in the feed;
            # consumers can still poll via ``read_assets`` or the HTTP API.
            pass


class ReadAssetsTool(Tool):
    """Read asset feed entries with cursor + kind filters."""

    def __init__(self, feed: AssetFeedSource) -> None:
        self._feed = feed

    @property
    def name(self) -> str:
        return "read_assets"

    @property
    def description(self) -> str:
        return (
            "Read entries from the shared asset feed. Use ``since_id`` to "
            "consume only the deltas pushed since your last read. Optional "
            "``kind`` filters to one asset kind (url / port / service / "
            "credential / vuln / tech). Returns a JSON list of "
            "{id, kind, agent_name, payload, created_at}, capped at 200 "
            "entries per call."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "description": "Optional kind filter.",
                },
                "since_id": {
                    "type": "integer",
                    "description": (
                        "Return only entries with id strictly greater "
                        "than this value. Use 0 (or omit) for a full "
                        "snapshot."
                    ),
                    "minimum": 0,
                },
            },
        }

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> str:
        kind_raw = kwargs.get("kind")
        kind: str | None = None
        if isinstance(kind_raw, str) and kind_raw.strip():
            kind = kind_raw.strip().lower()
        since_raw = kwargs.get("since_id")
        since_id: int | None = None
        if isinstance(since_raw, int) and since_raw >= 0:
            since_id = since_raw

        feed = _resolve(self._feed)
        entries = await feed.since(since_id=since_id, kind=kind)
        if not entries:
            return "No new assets."
        return json.dumps([e.to_dict() for e in entries], ensure_ascii=False)

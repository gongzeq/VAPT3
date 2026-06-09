"""Asset feed read/write tools for sub-agents.

The asset feed is the inter-agent communication channel for **discrete
asset discoveries** (URL / port / service / credential / vuln / tech).
``asset_push`` writes one entry per discovery and wakes the orchestrator
via the message bus; ``read_assets`` reads with cursor-based pagination.
See :mod:`secbot.agent.asset_feed` for the underlying registry.

Auto-flush: when ``kind`` is ``vuln``, ``credential``, or ``tech``,
``AssetPushTool`` can persist the discovery to the CMDB, but only when the
current session's Asset Auto-Management switch is enabled. Disabled sessions
keep discoveries transient in this feed.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from secbot.agent.asset_feed import KNOWN_ASSET_KINDS, AssetFeed
from secbot.agent.tools.base import Tool
from secbot.bus.events import InboundMessage
from secbot.bus.queue import MessageBus

_logger = logging.getLogger(__name__)

AssetFeedSource = AssetFeed | Callable[[], AssetFeed]

# Kinds that are automatically flushed to the CMDB.
_CMDB_FLUSH_KINDS: frozenset[str] = frozenset({"vuln", "credential", "tech"})

# Map free-form vuln type strings to the CMDB-valid category vocabulary.
# See :data:`secbot.cmdb.models.VALID_VULN_CATEGORIES`.
_VALID_CATEGORIES = frozenset({
    "injection", "auth", "xss", "misconfig",
    "exposure", "weak_password", "cve", "other",
})
_CATEGORY_MAP: dict[str, str] = {
    "sqli": "injection",
    "sql_injection": "injection",
    "nosql_injection": "injection",
    "command_injection": "injection",
    "rce": "injection",
    "ssti": "injection",
    "xxe": "injection",
    "lfi": "exposure",
    "rfi": "exposure",
    "directory_traversal": "exposure",
    "path_traversal": "exposure",
    "info_leak": "exposure",
    "info_disclosure": "exposure",
    "sensitive_data": "exposure",
    "file_upload": "exposure",
    "file_inclusion": "exposure",
    "ssrf": "misconfig",
    "open_redirect": "misconfig",
    "csrf": "xss",
    "reflected_xss": "xss",
    "stored_xss": "xss",
    "dom_xss": "xss",
    "brute_force": "weak_password",
    "default_credentials": "weak_password",
    "weak_password": "weak_password",
    "broken_auth": "auth",
    "auth_bypass": "auth",
    "id": "auth",
    "insecure_deserialization": "other",
    "deserialization": "other",
}


def _resolve(source: AssetFeedSource) -> AssetFeed:
    return source() if callable(source) else source


# ---------------------------------------------------------------------------
# Asset payload → CMDB write-instruction converters
# ---------------------------------------------------------------------------


def _host_from_url(url: str) -> str:
    """Extract ``host[:port]`` from *url*, falling back to the raw string."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname or url
        if parsed.port and parsed.port not in (80, 443):
            return f"{host}:{parsed.port}"
        return host
    except Exception:
        return url


def _normalise_category(raw: str) -> str:
    """Map a free-form vuln type to a CMDB-valid category."""
    if raw in _VALID_CATEGORIES:
        return raw
    return _CATEGORY_MAP.get(raw.lower().replace(" ", "_"), "other")


def _vuln_to_cmdb_write(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Convert a ``kind=vuln`` asset payload to a CMDB vulnerability write."""
    url = payload.get("url", "")
    target = (
        payload.get("target")
        or (_host_from_url(url) if url else None)
        or payload.get("host", "")
    )
    if not target:
        return None
    return {
        "table": "vulnerabilities",
        "op": "upsert",
        "data": {
            "target": target,
            "severity": payload.get("severity", "info"),
            "category": _normalise_category(payload.get("type") or payload.get("category", "other")),
            "title": payload.get("title") or f"{payload.get('type', 'vuln')} on {url or target}",
            "evidence": payload.get("evidence", ""),
            "cve_id": payload.get("cve_id"),
        },
    }


def _credential_to_cmdb_write(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Convert a ``kind=credential`` asset payload to a CMDB vulnerability write."""
    host = payload.get("host") or payload.get("target", "")
    if not host:
        return None
    port = payload.get("port")
    target = f"{host}:{port}" if port else host
    return {
        "table": "vulnerabilities",
        "op": "upsert",
        "data": {
            "target": target,
            "severity": "critical",
            "category": "weak_password",
            "title": payload.get("title") or f"Credential leak: {payload.get('username', '?')}@{target}",
            "evidence": (
                f"username={payload.get('username', '')} "
                f"password={payload.get('password', '')} "
                f"db={payload.get('db', '')} "
                f"type={payload.get('type', '')} "
                f"{payload.get('note', '')}"
            ).strip(),
        },
    }


def _tech_to_cmdb_write(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Convert a ``kind=tech`` asset payload to a CMDB asset write."""
    url = payload.get("url", "")
    target = (
        payload.get("target")
        or (_host_from_url(url) if url else None)
        or ""
    )
    if not target:
        return None
    return {
        "table": "assets",
        "op": "upsert",
        "data": {
            "target": target,
            "tags": {
                k: v for k, v in {
                    "server": payload.get("server"),
                    "platform": payload.get("platform"),
                    "os": payload.get("os"),
                    "php": payload.get("php"),
                    "mysql": payload.get("mysql"),
                }.items() if v
            },
            "os_guess": payload.get("os"),
        },
    }


_KIND_CONVERTERS: dict[str, Callable[[dict[str, Any]], dict[str, Any] | None]] = {
    "vuln": _vuln_to_cmdb_write,
    "credential": _credential_to_cmdb_write,
    "tech": _tech_to_cmdb_write,
}


async def _flush_asset_to_cmdb(
    kind: str,
    payload: dict[str, Any],
    *,
    agent_name: str,
) -> bool:
    """Best-effort persist a single asset discovery to the CMDB.

    Reads ``scan_id`` from the SkillContext ContextVar so it stays
    consistent with the rest of the scan pipeline.  Returns ``True`` on
    success, ``False`` on any failure (logged as warning).
    """
    if kind not in _CMDB_FLUSH_KINDS:
        return False

    converter = _KIND_CONVERTERS.get(kind)
    if converter is None:
        return False

    write = converter(payload)
    if write is None:
        _logger.debug("asset_push cmdb flush: converter returned None for kind=%s", kind)
        return False

    try:
        from secbot.agent.tools.skill import (
            _scan_id_var,
            current_asset_auto_management_enabled,
        )
        from secbot.cmdb.db import get_session
        from secbot.cmdb.models import DEFAULT_ACTOR
        from secbot.cmdb.repo import create_scan, get_scan
        from secbot.cmdb.writes import apply_cmdb_writes

        if not current_asset_auto_management_enabled():
            _logger.debug(
                "asset_push cmdb flush skipped for kind=%s: asset auto-management disabled",
                kind,
            )
            return False

        scan_id = _scan_id_var.get()
        async with get_session() as session:
            # Ensure the scan record exists before writing assets/vulns —
            # the FK constraint (asset.scan_id → scan.id) will reject the
            # insert otherwise.
            scan = await get_scan(session, DEFAULT_ACTOR, scan_id)
            if scan is None:
                # Derive a human-readable target from the payload.
                target = (
                    payload.get("target")
                    or payload.get("host")
                    or payload.get("url", "")
                    or scan_id
                )
                await create_scan(
                    session, DEFAULT_ACTOR, target=target, scan_id=scan_id
                )
            await apply_cmdb_writes(
                session,
                DEFAULT_ACTOR,
                scan_id,
                [write],
                discovered_by=agent_name,
            )
        return True
    except Exception:
        _logger.warning(
            "asset_push cmdb flush failed for kind=%s", kind, exc_info=True
        )
        return False


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

        # Auto-flush vuln / credential / tech discoveries to the CMDB so
        # that ``report-html`` can render a complete report without a
        # separate flush step.  Best-effort: never fail the push.
        flushed = await _flush_asset_to_cmdb(
            kind, payload, agent_name=self._agent_name
        )

        kinds_hint = (
            "" if kind in KNOWN_ASSET_KINDS
            else f" (note: kind '{kind}' is non-standard)"
        )
        cmdb_hint = " +cmdb" if flushed else ""
        return f"asset pushed (id={entry.id}, kind={kind}){cmdb_hint}{kinds_hint}"

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
                        f"Call read_assets with since_id={max(entry_id - 1, 0)} "
                        "to consume this entry, or omit since_id for a full "
                        "snapshot. Then decide if a downstream agent should "
                        "be dispatched."
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

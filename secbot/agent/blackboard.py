"""Task-scoped shared blackboard for inter-agent communication."""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

# Legacy free-text tags. The REST/WS contract still exposes these when legacy
# callers write ``"[finding] ..."`` text.
LEGACY_KINDS: tuple[str, ...] = ("milestone", "blocker", "finding", "progress")
KNOWN_KINDS: tuple[str, ...] = LEGACY_KINDS

# Structured kinds for the Pi blackboard migration. New writes must use one
# of these values; legacy text without a known tag becomes ``legacy_text``.
STRUCTURED_KINDS: tuple[str, ...] = (
    "scope",
    "phase_transition",
    "finding",
    "hypothesis",
    "evidence_ref",
    "approval",
    "milestone",
    "blocker",
    "progress",
    "summary",
    "legacy_text",
)
Kind = Literal[
    "scope",
    "phase_transition",
    "finding",
    "hypothesis",
    "evidence_ref",
    "approval",
    "milestone",
    "blocker",
    "progress",
    "summary",
    "legacy_text",
]
Phase = Literal[
    "Intake",
    "Passive Discovery",
    "Active Mapping",
    "Hypothesis Generation",
    "Safe Validation",
    "Triage",
    "Reporting",
    "Checkpoint",
]

PHASES: tuple[str, ...] = (
    "Intake",
    "Passive Discovery",
    "Active Mapping",
    "Hypothesis Generation",
    "Safe Validation",
    "Triage",
    "Reporting",
    "Checkpoint",
)

SEVERITY_ORDER: dict[str, int] = {
    "critical": 5,
    "high": 4,
    "medium": 3,
    "low": 2,
    "info": 1,
    "unknown": 0,
}

_KIND_PREFIX_RE = re.compile(
    r"^\s*\[(" + "|".join(LEGACY_KINDS) + r")\]",
    flags=re.IGNORECASE,
)
_ANY_PREFIX_RE = re.compile(r"^\s*\[[^\]]+\]\s*")

_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "scope": ("in_scope", "out_of_scope"),
    "phase_transition": ("from", "to", "reason"),
    "finding": ("title", "severity", "cwe", "owasp_category", "asset_ref", "evidence_ids"),
    "hypothesis": ("title", "kind", "confidence"),
    "evidence_ref": ("evidence_id", "source_tool", "summary"),
    "approval": ("action", "requested_at", "state"),
    "milestone": ("summary",),
    "blocker": ("summary",),
    "progress": ("summary",),
    "summary": ("kind", "items"),
    "legacy_text": ("text",),
}

_OPTIONAL_FIELDS: dict[str, tuple[str, ...]] = {
    "scope": ("auth_window", "forbidden_actions", "risk_profile"),
    "phase_transition": (),
    "finding": ("confidence", "remediation_ref", "chain_of"),
    "hypothesis": ("needs_skills", "evidence_ids"),
    "evidence_ref": (),
    "approval": ("justification", "denial_reason", "decided_at"),
    "milestone": ("phase",),
    "blocker": ("kind", "requires_human"),
    "progress": ("done", "total"),
    "summary": (),
    "legacy_text": (),
}

_HYPOTHESIS_KINDS = frozenset(
    {"input-validation", "authz", "ssrf", "business-logic", "other"}
)
_APPROVAL_STATES = frozenset({"pending", "approved", "denied"})
_BLOCKER_KINDS = frozenset({"scope", "creds", "tool_missing", "other"})
_SUMMARY_KINDS = frozenset({"findings_summary", "blockers_summary", "next_steps"})


class BlackboardValueError(ValueError):
    """Raised when a structured blackboard write violates the kind schema."""


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
    timestamp: float
    kind: str | None = None
    payload: dict[str, Any] | None = None
    text: str | None = None

    def to_dict(self) -> dict:
        """Serialize this entry for JSON transport.

        The first five fields are the legacy REST/WS contract. ``payload`` is
        additive so existing consumers can keep reading ``text`` and ``kind``.
        """
        payload = {
            "id": self.id,
            "agent_name": self.agent_name,
            "text": self.text,
            "timestamp": self.timestamp,
            "kind": self.kind,
        }
        payload["payload"] = dict(self.payload or {})
        return payload


@dataclass(frozen=True, slots=True)
class BlackboardSnapshot:
    """Aggregated view injected into the Pi prompt."""

    scope: dict[str, Any] | None
    current_phase: str
    findings: list[dict[str, Any]]
    open_hypotheses: list[dict[str, Any]]
    pending_approvals: list[dict[str, Any]]
    recent_blockers: list[dict[str, Any]]
    recent_milestones: list[dict[str, Any]]
    truncated_findings: int = 0
    truncated_hypotheses: int = 0

    def to_markdown(self) -> str:
        """Render a compact markdown snapshot for LLM tool results."""
        lines: list[str] = ["## Blackboard Snapshot", f"- Current phase: {self.current_phase}"]
        if self.scope:
            in_scope = ", ".join(map(str, self.scope.get("in_scope", []))) or "none"
            out_of_scope = ", ".join(map(str, self.scope.get("out_of_scope", []))) or "none"
            lines.append(f"- Scope: in={in_scope}; out={out_of_scope}")
        else:
            lines.append("- Scope: not set")

        def append_items(title: str, items: list[dict[str, Any]], *, field: str = "summary") -> None:
            lines.append(f"\n### {title}")
            if not items:
                lines.append("- none")
                return
            for item in items:
                value = item.get(field) or item.get("title") or item.get("action") or "untitled"
                lines.append(f"- {value}")

        append_items("Findings", self.findings, field="title")
        if self.truncated_findings:
            lines.append(f"- ... ({self.truncated_findings} more, see read_blackboard_full)")
        append_items("Open Hypotheses", self.open_hypotheses, field="title")
        if self.truncated_hypotheses:
            lines.append(f"- ... ({self.truncated_hypotheses} more, see read_blackboard_full)")
        append_items("Pending Approvals", self.pending_approvals, field="action")
        append_items("Recent Blockers", self.recent_blockers)
        append_items("Recent Milestones", self.recent_milestones)
        return "\n".join(lines)


def _summary_from_text(text: str) -> str:
    return _ANY_PREFIX_RE.sub("", text, count=1).strip()


def _validate_summary(value: Any, *, field: str = "summary", max_chars: int | None = None) -> None:
    if not isinstance(value, str) or not value.strip():
        raise BlackboardValueError(f"{field} must be a non-empty string")
    if max_chars is not None and len(value) > max_chars:
        raise BlackboardValueError(f"{field} must be <= {max_chars} chars")


def _validate_string_list(value: Any, *, field: str) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise BlackboardValueError(f"{field} must be a list[str]")


def _normalise_kind(kind: str) -> str:
    normalised = kind.strip().lower()
    if normalised not in STRUCTURED_KINDS:
        raise BlackboardValueError(f"unknown kind: {kind}")
    return normalised


def _normalise_payload(kind: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise BlackboardValueError("payload must be an object")

    data = dict(payload)
    required = _REQUIRED_FIELDS[kind]
    missing = [field for field in required if field not in data]
    if missing:
        raise BlackboardValueError(f"{kind} payload missing required field(s): {', '.join(missing)}")

    allowed = set(required) | set(_OPTIONAL_FIELDS[kind])
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise BlackboardValueError(f"{kind} payload has unknown field(s): {', '.join(unknown)}")

    if kind == "scope":
        _validate_string_list(data["in_scope"], field="in_scope")
        _validate_string_list(data["out_of_scope"], field="out_of_scope")
    elif kind == "phase_transition":
        if data["from"] not in PHASES:
            raise BlackboardValueError("from must be a valid phase")
        if data["to"] not in PHASES:
            raise BlackboardValueError("to must be a valid phase")
        _validate_summary(data["reason"], field="reason")
    elif kind == "finding":
        for field in ("title", "severity", "cwe", "owasp_category", "asset_ref"):
            _validate_summary(data[field], field=field)
        _validate_string_list(data["evidence_ids"], field="evidence_ids")
        data["severity"] = str(data["severity"]).lower()
    elif kind == "hypothesis":
        _validate_summary(data["title"], field="title")
        if data["kind"] not in _HYPOTHESIS_KINDS:
            raise BlackboardValueError("hypothesis kind must be one of input-validation/authz/ssrf/business-logic/other")
        confidence = data["confidence"]
        if not isinstance(confidence, int | float) or not 0 <= float(confidence) <= 1:
            raise BlackboardValueError("confidence must be a number between 0 and 1")
        data["confidence"] = float(confidence)
        if "evidence_ids" in data:
            _validate_string_list(data["evidence_ids"], field="evidence_ids")
        if "needs_skills" in data:
            _validate_string_list(data["needs_skills"], field="needs_skills")
    elif kind == "evidence_ref":
        _validate_summary(data["evidence_id"], field="evidence_id")
        _validate_summary(data["source_tool"], field="source_tool")
        _validate_summary(data["summary"], max_chars=200)
    elif kind == "approval":
        for field in ("action", "requested_at", "state"):
            _validate_summary(str(data[field]), field=field)
        if data["state"] not in _APPROVAL_STATES:
            raise BlackboardValueError("state must be pending/approved/denied")
    elif kind in {"milestone", "blocker", "progress"}:
        _validate_summary(data["summary"])
        if kind == "blocker" and "kind" in data and data["kind"] not in _BLOCKER_KINDS:
            raise BlackboardValueError("blocker kind must be scope/creds/tool_missing/other")
    elif kind == "summary":
        if data["kind"] not in _SUMMARY_KINDS:
            raise BlackboardValueError("summary kind must be findings_summary/blockers_summary/next_steps")
        _validate_string_list(data["items"], field="items")
    elif kind == "legacy_text":
        if not isinstance(data["text"], str):
            raise BlackboardValueError("text must be a string")

    return data


def _legacy_payload(kind: str | None, text: str) -> tuple[str, dict[str, Any]]:
    summary = _summary_from_text(text) or text.strip()
    if kind == "finding":
        return (
            "finding",
            {
                "title": summary,
                "severity": "unknown",
                "cwe": "unknown",
                "owasp_category": "unknown",
                "asset_ref": "unknown",
                "evidence_ids": [],
            },
        )
    if kind in {"milestone", "blocker", "progress"}:
        return kind, {"summary": summary}
    return "legacy_text", {"text": text}


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

    async def write(
        self,
        agent_name: str,
        text: str,
        payload: Mapping[str, Any] | None = None,
    ) -> BlackboardEntry:
        """Write a new entry to the blackboard.

        Compatibility:
        - ``write(agent, text)`` remains the legacy free-text API.
        - ``write(agent, kind, payload)`` is the structured PR1 API.
        """
        if payload is None:
            return await self.write_text(agent_name, text)

        kind = _normalise_kind(text)
        normalised_payload = _normalise_payload(kind, payload)
        entry = BlackboardEntry(
            id=str(uuid.uuid4())[:8],
            agent_name=agent_name,
            timestamp=time.time(),
            kind=kind,
            payload=normalised_payload,
            text=None,
        )
        await self._append(entry)
        return entry

    async def write_text(self, agent_name: str, text: str) -> BlackboardEntry:
        """Write a legacy free-text entry and translate known tags to payloads."""
        if not isinstance(text, str):
            raise BlackboardValueError("text must be a string")
        legacy_kind = _extract_kind(text)
        structured_kind, payload = _legacy_payload(legacy_kind, text)
        kind = legacy_kind if legacy_kind is not None else structured_kind
        entry = BlackboardEntry(
            id=str(uuid.uuid4())[:8],
            agent_name=agent_name,
            timestamp=time.time(),
            kind=kind,
            payload=payload,
            text=text,
        )
        _normalise_payload(structured_kind, payload)
        await self._append(entry)
        return entry

    async def _append(self, entry: BlackboardEntry) -> None:
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

    async def read_all(self) -> list[BlackboardEntry]:
        """Read all entries (returns a copy for safety)."""
        async with self._lock:
            return list(self._entries)

    async def read(
        self,
        *,
        limit: int | None = None,
        kinds: Iterable[str] | None = None,
    ) -> list[BlackboardEntry]:
        """Legacy-compatible read API with optional limit/kind filtering."""
        entries = await self.read_all()
        if kinds is not None:
            requested = {_normalise_kind(kind) for kind in kinds}
            entries = [entry for entry in entries if entry.kind in requested]
        if limit is not None:
            entries = entries[-limit:]
        return entries

    async def read_by_kind(
        self,
        kinds: Iterable[str],
        *,
        since: float | None = None,
        scope_filter: Any | None = None,
    ) -> list[BlackboardEntry]:
        """Read typed entries matching ``kinds``.

        ``scope_filter`` is accepted for the future PolicyEngine integration;
        PR1 keeps the board in-memory and does not enforce scope filtering.
        """
        del scope_filter
        requested = {_normalise_kind(kind) for kind in kinds}
        async with self._lock:
            return [
                entry
                for entry in self._entries
                if entry.kind in requested and (since is None or entry.timestamp >= since)
            ]

    async def snapshot(self) -> BlackboardSnapshot:
        """Return an aggregated prompt-sized view of the structured board."""
        entries = await self.read_all()
        latest_scope: dict[str, Any] | None = None
        current_phase = "Intake"
        findings: list[dict[str, Any]] = []
        hypotheses: list[dict[str, Any]] = []
        pending_approvals: list[dict[str, Any]] = []
        blockers: list[dict[str, Any]] = []
        milestones: list[dict[str, Any]] = []

        for entry in entries:
            payload = dict(entry.payload or {})
            if entry.kind == "scope":
                latest_scope = payload
            elif entry.kind == "phase_transition":
                current_phase = str(payload.get("to", current_phase))
            elif entry.kind == "finding":
                findings.append(self._snapshot_payload(entry, payload))
            elif entry.kind == "hypothesis":
                hypotheses.append(self._snapshot_payload(entry, payload))
            elif entry.kind == "approval" and payload.get("state") == "pending":
                pending_approvals.append(self._snapshot_payload(entry, payload))
            elif entry.kind == "blocker":
                blockers.append(self._snapshot_payload(entry, payload))
            elif entry.kind == "milestone":
                milestones.append(self._snapshot_payload(entry, payload))

        findings.sort(
            key=lambda item: (
                SEVERITY_ORDER.get(str(item.get("severity", "unknown")).lower(), 0),
                item.get("created_at", 0.0),
            ),
            reverse=True,
        )
        hypotheses.sort(key=lambda item: float(item.get("confidence", 0)), reverse=True)

        return BlackboardSnapshot(
            scope=latest_scope,
            current_phase=current_phase,
            findings=findings[:50],
            open_hypotheses=hypotheses[:20],
            pending_approvals=pending_approvals,
            recent_blockers=blockers[-5:],
            recent_milestones=milestones[-5:],
            truncated_findings=max(0, len(findings) - 50),
            truncated_hypotheses=max(0, len(hypotheses) - 20),
        )

    @staticmethod
    def _snapshot_payload(entry: BlackboardEntry, payload: dict[str, Any]) -> dict[str, Any]:
        item = dict(payload)
        item.setdefault("id", entry.id)
        item.setdefault("created_at", entry.timestamp)
        if entry.text and "summary" not in item and "title" not in item:
            item["summary"] = _summary_from_text(entry.text) or entry.text
        return item

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

"""Session JSONL source for report rendering.

`report-html` renders the current scan from persisted session events. The
source of truth is the session JSONL file under ``<workspace>/sessions``;
Managed Assets/CMDB rows are not required for report content.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from secbot.report.builder import ReportModel, build_report_model_from_asset_entries
from secbot.session.manager import SessionManager

_logger = logging.getLogger(__name__)

_ASSET_PUSH_ID_RE = re.compile(r"asset pushed \(id=(\d+),")


@dataclass(frozen=True)
class SessionReportSource:
    """Report model plus the session file it came from."""

    model: ReportModel
    session_path: Path | None
    entry_count: int


def workspace_from_scan_dir(scan_dir: Path) -> Path:
    """Infer the workspace root from a skill scan directory."""

    if scan_dir.parent.name == "scans" and scan_dir.parent.parent.name in {
        ".secbot",
        "secbot",
    }:
        return scan_dir.parent.parent.parent
    return scan_dir.parent


def find_session_jsonl(workspace: Path, scan_id: str) -> Path | None:
    """Return the persisted session JSONL path for *scan_id*, if present."""

    sessions_dir = workspace / "sessions"
    candidates: list[str] = [scan_id]
    if "_" in scan_id:
        candidates.append(scan_id.replace("_", ":", 1))

    seen: set[Path] = set()
    for candidate in candidates:
        path = sessions_dir / f"{SessionManager.safe_key(candidate)}.jsonl"
        if path in seen:
            continue
        seen.add(path)
        if path.exists():
            return path
    return None


def load_asset_entries_from_session_jsonl(path: Path) -> list[dict[str, Any]]:
    """Extract successful ``asset_push`` tool calls from a session JSONL file."""

    entries: list[dict[str, Any]] = []
    read_assets_snapshots: list[list[dict[str, Any]]] = []
    seen_tool_call_ids: set[str] = set()

    try:
        with path.open(encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    _logger.warning(
                        "report session source skipped invalid JSON: path=%s line=%d",
                        path,
                        line_no,
                    )
                    continue
                if not isinstance(row, dict):
                    continue
                event = row.get("agent_event") if row.get("_kind") == "agent_event" else None
                if not isinstance(event, dict) or event.get("type") != "tool_call":
                    continue

                if event.get("status") != "ok":
                    continue

                tool_name = event.get("tool_name")
                if tool_name == "asset_push":
                    entry = _entry_from_asset_push_event(row, event, len(entries) + 1)
                    if entry is None:
                        continue
                    tool_call_id = str(event.get("tool_call_id") or "")
                    if tool_call_id:
                        if tool_call_id in seen_tool_call_ids:
                            continue
                        seen_tool_call_ids.add(tool_call_id)
                    entries.append(entry)
                elif tool_name == "read_assets":
                    snapshot = _read_assets_snapshot(event)
                    if snapshot:
                        read_assets_snapshots.append(snapshot)
    except FileNotFoundError:
        return []
    except OSError:
        _logger.warning("report session source failed to read %s", path, exc_info=True)
        return []

    if entries:
        return entries
    if read_assets_snapshots:
        return read_assets_snapshots[-1]
    return []


def build_report_model_from_session_jsonl(
    workspace: Path,
    scan_id: str,
    *,
    target: str | None = None,
) -> SessionReportSource:
    """Build a report model from the persisted session JSONL for *scan_id*."""

    session_path = find_session_jsonl(workspace, scan_id)
    entries = (
        load_asset_entries_from_session_jsonl(session_path)
        if session_path is not None
        else []
    )
    model = build_report_model_from_asset_entries(
        entries,
        scan_id=scan_id,
        target=target,
    )
    return SessionReportSource(
        model=model,
        session_path=session_path,
        entry_count=len(entries),
    )


def _entry_from_asset_push_event(
    row: dict[str, Any],
    event: dict[str, Any],
    fallback_id: int,
) -> dict[str, Any] | None:
    tool_args = event.get("tool_args")
    if not isinstance(tool_args, dict):
        return None

    kind = str(tool_args.get("kind") or "").strip().lower()
    payload = tool_args.get("payload")
    if not kind or not isinstance(payload, dict):
        return None

    return {
        "id": _asset_push_id(event.get("detail")) or fallback_id,
        "kind": kind,
        "agent_name": str(
            event.get("agent_name")
            or event.get("agent")
            or row.get("sender_id")
            or "session_jsonl"
        ),
        "payload": payload,
        "created_at": _timestamp_to_epoch(row.get("timestamp")),
    }


def _read_assets_snapshot(event: dict[str, Any]) -> list[dict[str, Any]]:
    detail = event.get("detail")
    if not isinstance(detail, str) or not detail.strip():
        return []
    try:
        raw = json.loads(detail)
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []

    entries: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        payload = item.get("payload")
        if not isinstance(payload, dict):
            continue
        kind = str(item.get("kind") or "").strip().lower()
        if not kind:
            continue
        entries.append(
            {
                "id": item.get("id") or len(entries) + 1,
                "kind": kind,
                "agent_name": str(item.get("agent_name") or "read_assets"),
                "payload": payload,
                "created_at": item.get("created_at"),
            }
        )
    return entries


def _asset_push_id(detail: object) -> int | None:
    if not isinstance(detail, str):
        return None
    match = _ASSET_PUSH_ID_RE.search(detail)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _timestamp_to_epoch(raw: object) -> float | None:
    if isinstance(raw, (int, float)):
        return float(raw)
    if not isinstance(raw, str) or not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()

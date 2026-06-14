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

from secbot.agent.vulnerability_store import (
    VALID_SEVERITIES,
    VALID_VERIFICATION_METHODS,
)
from secbot.report.builder import (
    ReportModel,
    build_report_model_from_asset_entries,
    build_report_model_from_vulnerabilities,
    merge_report_models,
)
from secbot.session.manager import SessionManager

_logger = logging.getLogger(__name__)

_ASSET_PUSH_ID_RE = re.compile(r"asset pushed \(id=(\d+),")
_ASSET_PUSH_BATCH_ID_RE = re.compile(r"assets pushed \(ids=(\d+)\.\.")
_REPORT_VULN_ID_RE = re.compile(r"vulnerability reported \(id=(\d+),")


@dataclass(frozen=True)
class SessionReportSource:
    """Report model plus the session file it came from."""

    model: ReportModel
    session_path: Path | None
    entry_count: int


@dataclass(frozen=True)
class SessionReportEntries:
    """Structured report-relevant entries extracted from a session JSONL."""

    asset_entries: list[dict[str, Any]]
    vulnerability_entries: list[dict[str, Any]]

    @property
    def count(self) -> int:
        return len(self.asset_entries) + len(self.vulnerability_entries)


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

    return load_report_entries_from_session_jsonl(path).asset_entries


def load_report_entries_from_session_jsonl(path: Path) -> SessionReportEntries:
    """Extract report data from successful session tool-call events."""

    asset_entries: list[dict[str, Any]] = []
    vulnerability_entries: list[dict[str, Any]] = []
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
                if tool_name in {"asset_push", "report_vulnerability"}:
                    tool_call_id = str(event.get("tool_call_id") or "")
                    if tool_call_id and tool_call_id in seen_tool_call_ids:
                        continue
                    fallback_id = len(asset_entries) + len(vulnerability_entries) + 1
                    if tool_name == "asset_push":
                        new_entries = _entries_from_asset_push_event(
                            row, event, fallback_id
                        )
                        if not new_entries:
                            continue
                        asset_entries.extend(new_entries)
                    else:
                        new_entry = _entry_from_report_vulnerability_event(
                            row, event, fallback_id
                        )
                        if new_entry is None:
                            continue
                        vulnerability_entries.append(new_entry)
                    if tool_call_id:
                        seen_tool_call_ids.add(tool_call_id)
                elif tool_name == "read_assets":
                    snapshot = _read_assets_snapshot(event)
                    if snapshot:
                        read_assets_snapshots.append(snapshot)
    except FileNotFoundError:
        return SessionReportEntries(asset_entries=[], vulnerability_entries=[])
    except OSError:
        _logger.warning("report session source failed to read %s", path, exc_info=True)
        return SessionReportEntries(asset_entries=[], vulnerability_entries=[])

    if not asset_entries and read_assets_snapshots:
        # Incremental ``since_id`` reads each return only a delta, so taking
        # just the last snapshot would undercount. Union every snapshot by
        # real feed id (id-less rows are always kept).
        merged: dict[Any, dict[str, Any]] = {}
        extra: list[dict[str, Any]] = []
        for snapshot in read_assets_snapshots:
            for item in snapshot:
                key = item.get("id")
                if key is None:
                    extra.append(item)
                else:
                    merged[key] = item
        asset_entries = list(merged.values()) + extra
    return SessionReportEntries(
        asset_entries=asset_entries,
        vulnerability_entries=vulnerability_entries,
    )


def build_report_model_from_session_jsonl(
    workspace: Path,
    scan_id: str,
    *,
    target: str | None = None,
) -> SessionReportSource:
    """Build a report model from the persisted session JSONL for *scan_id*."""

    session_path = find_session_jsonl(workspace, scan_id)
    entries = (
        load_report_entries_from_session_jsonl(session_path)
        if session_path is not None
        else SessionReportEntries(asset_entries=[], vulnerability_entries=[])
    )
    asset_model = build_report_model_from_asset_entries(
        entries.asset_entries,
        scan_id=scan_id,
        target=target,
    )
    vulnerability_model = build_report_model_from_vulnerabilities(
        entries.vulnerability_entries,
        scan_id=scan_id,
        target=target,
    )
    model = merge_report_models(vulnerability_model, asset_model)
    return SessionReportSource(
        model=model,
        session_path=session_path,
        entry_count=entries.count,
    )


def load_interrupted_subagents_from_session_jsonl(path: Path | None) -> list[dict[str, Any]]:
    """Return latest interrupted subagent rows from a persisted session JSONL."""
    if path is None:
        return []

    latest_by_agent: dict[str, dict[str, Any]] = {}
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
                if not isinstance(event, dict) or event.get("type") != "subagent_done":
                    continue
                agent_name = str(
                    event.get("agent_name")
                    or event.get("label")
                    or row.get("sender_id")
                    or "unknown"
                )
                latest_by_agent[agent_name] = {
                    "agent_name": agent_name,
                    "task_id": event.get("task_id"),
                    "status": str(event.get("status") or "").strip().lower(),
                    "label": event.get("label"),
                    "timestamp": row.get("timestamp"),
                }
    except FileNotFoundError:
        return []
    except OSError:
        _logger.warning("report session source failed to read %s", path, exc_info=True)
        return []

    return [
        item
        for item in latest_by_agent.values()
        if item["status"] in {"incomplete", "interrupted"}
    ]


def _entries_from_asset_push_event(
    row: dict[str, Any],
    event: dict[str, Any],
    fallback_id: int,
) -> list[dict[str, Any]]:
    tool_args = event.get("tool_args")
    if not isinstance(tool_args, dict):
        return []

    kind = str(tool_args.get("kind") or "").strip().lower()
    if not kind:
        return []

    payloads: list[dict[str, Any]] = []
    payload = tool_args.get("payload")
    if isinstance(payload, dict):
        payloads.append(payload)
    raw_payloads = tool_args.get("payloads")
    if isinstance(raw_payloads, list):
        payloads.extend(item for item in raw_payloads if isinstance(item, dict))
    if not payloads:
        return []

    first_id = _asset_push_id(event.get("detail")) or fallback_id
    agent_name = str(
        event.get("agent_name")
        or event.get("agent")
        or row.get("sender_id")
        or "session_jsonl"
    )
    created_at = _timestamp_to_epoch(row.get("timestamp"))
    return [
        {
            "id": first_id + idx,
            "kind": kind,
            "agent_name": agent_name,
            "payload": item,
            "created_at": created_at,
        }
        for idx, item in enumerate(payloads)
    ]


def _entry_from_report_vulnerability_event(
    row: dict[str, Any],
    event: dict[str, Any],
    fallback_id: int,
) -> dict[str, Any] | None:
    tool_args = event.get("tool_args")
    if not isinstance(tool_args, dict):
        return None

    title = _required_str(tool_args.get("title"))
    severity = _required_str(tool_args.get("severity")).lower()
    description = _required_str(tool_args.get("description"))
    exploitation_proof = _required_str(tool_args.get("exploitation_proof"))
    verification_method = _required_str(tool_args.get("verification_method")).lower()
    if (
        not title
        or severity not in VALID_SEVERITIES
        or not description
        or not exploitation_proof
        or verification_method not in VALID_VERIFICATION_METHODS
    ):
        return None

    entry: dict[str, Any] = {
        "id": _report_vulnerability_id(event.get("detail")) or fallback_id,
        "agent_name": str(
            event.get("agent_name")
            or event.get("agent")
            or row.get("sender_id")
            or "report_vulnerability"
        ),
        "created_at": _timestamp_to_epoch(row.get("timestamp")),
        "title": title,
        "severity": severity,
        "description": description,
        "exploitation_proof": exploitation_proof,
        "verification_method": verification_method,
        "category": _optional_str(tool_args.get("category") or tool_args.get("type"))
        or "other",
    }

    cvss = _numeric(tool_args.get("cvss"))
    if cvss is not None:
        entry["cvss"] = cvss
    for key in (
        "endpoint",
        "poc_description",
        "poc_script_code",
        "remediation_steps",
    ):
        value = _optional_str(tool_args.get(key))
        if value:
            entry[key] = value
    return entry


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
    match = _ASSET_PUSH_ID_RE.search(detail) or _ASSET_PUSH_BATCH_ID_RE.search(detail)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _report_vulnerability_id(detail: object) -> int | None:
    if not isinstance(detail, str):
        return None
    match = _REPORT_VULN_ID_RE.search(detail)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _required_str(raw: object) -> str:
    return raw.strip() if isinstance(raw, str) else ""


def _optional_str(raw: object) -> str | None:
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _numeric(raw: object) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
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

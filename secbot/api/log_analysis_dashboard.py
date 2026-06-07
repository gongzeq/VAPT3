"""Read-only access layer for the log-analysis results DB.

The business SQLite (``<project_root>/detection_results.db``,
overridable via ``LOG_ANALYSIS_DB_PATH``) is written by the ``step2``
script of the log-analysis workflow (see :mod:`secbot.workflow.scripts`).
This module exposes the query primitives consumed by the dashboard REST
surface (``/api/dashboard/log-analysis/*``).

Design constraints:
* Strictly read-only — no schema migrations, no writes. The owner of
  this DB is the workflow step2 script.
* Open per-call short-lived connections (``timeout=1.5s``).
* Each function tolerates a missing DB file / table and returns an
  *empty* payload rather than raising.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

_DEFAULT_DB_PATH = str(Path(__file__).resolve().parents[2] / "detection_results.db")
_CONNECT_TIMEOUT_S = 1.5

# ---------------------------------------------------------------------------
# Status constants
# ---------------------------------------------------------------------------
STATUS_ALERT = "alert"
STATUS_HANDLED = "handled"
STATUS_NORMAL = "normal"

# Old suggested_action values → new two-value scheme (backward compat).
# New LLM outputs only "告警" / "正常"; legacy four-value outputs are mapped.
_ACTION_TO_STATUS: dict[str, str] = {
    "告警": STATUS_ALERT,
    "紧急处理": STATUS_ALERT,
    "正常": STATUS_NORMAL,
    "忽略": STATUS_NORMAL,
    "标记关注": STATUS_NORMAL,
}


def db_path() -> str:
    return os.environ.get("LOG_ANALYSIS_DB_PATH", _DEFAULT_DB_PATH)


def db_exists() -> bool:
    return os.path.isfile(db_path())


@contextmanager
def _connect() -> Iterator[sqlite3.Connection | None]:
    if not db_exists():
        yield None
        return
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(db_path(), timeout=_CONNECT_TIMEOUT_S)
        conn.row_factory = sqlite3.Row
        yield conn
    except sqlite3.Error:
        yield None
    finally:
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass


# ---------------------------------------------------------------------------
# L1 — latest result summary
# ---------------------------------------------------------------------------


def latest() -> dict[str, Any]:
    """Return the most recent log-analysis result.

    Returns an empty ``found`` key + zeroed fields when no data exists,
    so the frontend can render a meaningful "暂无数据" placeholder.
    """
    empty: dict[str, Any] = {
        "found": False,
        "id": 0,
        "file_name": "",
        "created_at": "",
        "anomaly_count": 0,
        "total_entries": 0,
        "char_count": 0,
        "log_format": "",
        "confidence": 0.0,
        "reason": "",
        "suggested_action": "",
        "risk_factors": [],
        "severity_distribution": {"critical": 0, "high": 0, "medium": 0, "low": 0, "safe": 0},
        "summary": "",
    }
    with _connect() as conn:
        if conn is None:
            return empty
        try:
            _ensure_handled_table(conn)
            row = conn.execute(
                """
                SELECT id, file_name, created_at, anomaly_count,
                       char_count, log_format,
                       summary, analysis_json
                FROM log_analysis
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
            handled_ids = _get_handled_ids(conn)
        except sqlite3.Error:
            return empty

    if row is None:
        return empty

    analysis: dict[str, Any] = {}
    try:
        analysis = json.loads(row["analysis_json"] or "{}")
    except (json.JSONDecodeError, TypeError):
        pass

    sev_dist = {
        "critical": int((analysis.get("severity_distribution") or {}).get("critical", 0)),
        "high": int((analysis.get("severity_distribution") or {}).get("high", 0)),
        "medium": int((analysis.get("severity_distribution") or {}).get("medium", 0)),
        "low": int((analysis.get("severity_distribution") or {}).get("low", 0)),
    }
    anomaly_total = sum(sev_dist.values())
    total_entries = int(analysis.get("total_entries") or 0) or int(row["anomaly_count"] or 0)
    sev_dist["safe"] = max(0, total_entries - anomaly_total)

    suggested_action = str(analysis.get("suggested_action") or "")
    row_id = int(row["id"])
    status = _derive_status(suggested_action, row_id in handled_ids)

    return {
        "found": True,
        "id": row_id,
        "file_name": row["file_name"] or "",
        "created_at": row["created_at"] or "",
        "anomaly_count": int(row["anomaly_count"] or 0),
        "total_entries": total_entries,
        "char_count": int(row["char_count"] or 0),
        "log_format": row["log_format"] or "",
        "confidence": float(analysis.get("confidence") or 0.0),
        "reason": str(analysis.get("reason") or ""),
        "suggested_action": suggested_action,
        "risk_factors": list(analysis.get("risk_factors") or []),
        "severity_distribution": sev_dist,
        "summary": row["summary"] or "",
        "status": status,
    }


# ---------------------------------------------------------------------------
# L2 — paginated history
# ---------------------------------------------------------------------------


def history(
    *,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """Paginated log-analysis result rows.

    Each row returns a subset of the full ``analysis_json`` fields
    sufficient for the list view. The caller can fetch the complete
    JSON blob via a detail endpoint if needed (for now it's inline).
    """
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 20), 200))
    offset = (page - 1) * page_size

    items: list[dict[str, Any]] = []
    total = 0

    with _connect() as conn:
        if conn is None:
            return {"items": [], "total": 0, "page": page, "page_size": page_size}
        try:
            _ensure_handled_table(conn)
            total = int(
                conn.execute("SELECT COUNT(*) FROM log_analysis").fetchone()[0] or 0
            )
            # Try to include total_entries column; fall back if not yet migrated
            try:
                rows = conn.execute(
                    """
                    SELECT id, file_name, created_at, anomaly_count,
                           critical_count, high_count, medium_count, low_count,
                           char_count, log_format, total_entries,
                           summary, analysis_json
                    FROM log_analysis
                    ORDER BY id DESC
                    LIMIT ? OFFSET ?
                    """,
                    (page_size, offset),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = conn.execute(
                    """
                    SELECT id, file_name, created_at, anomaly_count,
                           critical_count, high_count, medium_count, low_count,
                           char_count, log_format,
                           summary, analysis_json
                    FROM log_analysis
                    ORDER BY id DESC
                    LIMIT ? OFFSET ?
                    """,
                    (page_size, offset),
                ).fetchall()
            handled_ids = _get_handled_ids(conn)
        except sqlite3.Error:
            return {"items": [], "total": 0, "page": page, "page_size": page_size}

    for row in rows:
        analysis: dict[str, Any] = {}
        try:
            analysis = json.loads(row["analysis_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            pass

        sev_dist = {
            "critical": int(row["critical_count"] or 0),
            "high": int(row["high_count"] or 0),
            "medium": int(row["medium_count"] or 0),
            "low": int(row["low_count"] or 0),
        }
        anomaly_total = sum(sev_dist.values())
        try:
            total_entries_val = int(row["total_entries"] or 0) or int(row["anomaly_count"] or 0)
        except (IndexError, KeyError):
            total_entries_val = int(row["anomaly_count"] or 0)
        sev_dist["safe"] = max(0, total_entries_val - anomaly_total)

        row_id = int(row["id"])
        suggested_action = str(analysis.get("suggested_action") or "")
        status = _derive_status(suggested_action, row_id in handled_ids)

        items.append({
            "id": row_id,
            "file_name": row["file_name"] or "",
            "created_at": row["created_at"] or "",
            "anomaly_count": int(row["anomaly_count"] or 0),
            "total_entries": total_entries_val,
            "severity_distribution": sev_dist,
            "confidence": float(analysis.get("confidence") or 0.0),
            "reason": str(analysis.get("reason") or ""),
            "suggested_action": suggested_action,
            "risk_factors": list(analysis.get("risk_factors") or []),
            "anomaly_entries": list(analysis.get("anomaly_entries") or []),
            "summary": row["summary"] or "",
            "char_count": int(row["char_count"] or 0),
            "log_format": row["log_format"] or "unknown",
            "status": status,
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ---------------------------------------------------------------------------
# Handled table — separate write path (keeps log_analysis read-only)
# ---------------------------------------------------------------------------


def _ensure_handled_table(conn: sqlite3.Connection) -> None:
    """Create ``log_analysis_handled`` if it does not already exist.

    The table tracks which log-analysis records have been acknowledged by
    an operator.  Stored in the same DB file as ``log_analysis`` so that
    ``LEFT JOIN`` requires no extra connection.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS log_analysis_handled (
            log_id INTEGER PRIMARY KEY,
            handled_at TEXT NOT NULL
        )
        """
    )


def _derive_status(suggested_action: str, is_handled: bool) -> str:
    """Derive the three-state status from ``suggested_action`` + handled flag.

    Priority: ``handled > alert > normal``.  Unknown ``suggested_action``
    values default to *normal* so stale data never surfaces as alert.
    """
    if is_handled:
        return STATUS_HANDLED
    return _ACTION_TO_STATUS.get(suggested_action, STATUS_NORMAL)


def _get_handled_ids(conn: sqlite3.Connection) -> set[int]:
    """Return the set of log IDs that have been marked as handled."""
    try:
        rows = conn.execute(
            "SELECT log_id FROM log_analysis_handled"
        ).fetchall()
        return {int(r[0]) for r in rows}
    except sqlite3.OperationalError:
        return set()


def handle(log_id: int) -> dict[str, Any]:
    """Mark a log-analysis record as handled.

    Inserts into ``log_analysis_handled`` (idempotent — duplicate inserts
    are silently ignored via ``INSERT OR IGNORE``).  Returns the stored
    row including ``handled_at`` timestamp.
    """
    handled_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect() as conn:
        if conn is None:
            return {"ok": False, "error": "db_unavailable"}
        try:
            _ensure_handled_table(conn)
            conn.execute(
                "INSERT OR IGNORE INTO log_analysis_handled (log_id, handled_at)"
                " VALUES (?, ?)",
                (log_id, handled_at),
            )
            conn.commit()
        except sqlite3.Error as exc:
            return {"ok": False, "error": str(exc)}
    return {"ok": True, "log_id": log_id, "handled_at": handled_at}


def unhandle(log_id: int) -> dict[str, Any]:
    """Remove the handled mark from a log-analysis record (undo)."""
    with _connect() as conn:
        if conn is None:
            return {"ok": False, "error": "db_unavailable"}
        try:
            _ensure_handled_table(conn)
            conn.execute(
                "DELETE FROM log_analysis_handled WHERE log_id = ?",
                (log_id,),
            )
            conn.commit()
        except sqlite3.Error as exc:
            return {"ok": False, "error": str(exc)}
    return {"ok": True, "log_id": log_id}


def get_handled_log_ids() -> set[int]:
    """Return every log_id currently marked as handled (public accessor)."""
    with _connect() as conn:
        if conn is None:
            return set()
        _ensure_handled_table(conn)
        return _get_handled_ids(conn)


__all__ = (
    "latest",
    "history",
    "handle",
    "unhandle",
    "get_handled_log_ids",
    "db_path",
    "db_exists",
    "STATUS_ALERT",
    "STATUS_HANDLED",
    "STATUS_NORMAL",
)

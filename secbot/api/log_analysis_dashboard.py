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
from datetime import datetime
from typing import Any, Iterator

_DEFAULT_DB_PATH = "/home/administrator/VAPT3/detection_results.db"
_CONNECT_TIMEOUT_S = 1.5


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
        "confidence": 0.0,
        "reason": "",
        "suggested_action": "",
        "risk_factors": [],
        "severity_distribution": {"critical": 0, "high": 0, "medium": 0, "low": 0},
        "summary": "",
    }
    with _connect() as conn:
        if conn is None:
            return empty
        try:
            row = conn.execute(
                """
                SELECT id, file_name, created_at, anomaly_count,
                       summary, analysis_json
                FROM log_analysis
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
        except sqlite3.Error:
            return empty

    if row is None:
        return empty

    analysis: dict[str, Any] = {}
    try:
        analysis = json.loads(row["analysis_json"] or "{}")
    except (json.JSONDecodeError, TypeError):
        pass

    return {
        "found": True,
        "id": int(row["id"]),
        "file_name": row["file_name"] or "",
        "created_at": row["created_at"] or "",
        "anomaly_count": int(row["anomaly_count"] or 0),
        "confidence": float(analysis.get("confidence") or 0.0),
        "reason": str(analysis.get("reason") or ""),
        "suggested_action": str(analysis.get("suggested_action") or ""),
        "risk_factors": list(analysis.get("risk_factors") or []),
        "severity_distribution": {
            "critical": int((analysis.get("severity_distribution") or {}).get("critical", 0)),
            "high": int((analysis.get("severity_distribution") or {}).get("high", 0)),
            "medium": int((analysis.get("severity_distribution") or {}).get("medium", 0)),
            "low": int((analysis.get("severity_distribution") or {}).get("low", 0)),
        },
        "summary": row["summary"] or "",
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
            total = int(
                conn.execute("SELECT COUNT(*) FROM log_analysis").fetchone()[0] or 0
            )
            rows = conn.execute(
                """
                SELECT id, file_name, created_at, anomaly_count,
                       critical_count, high_count, medium_count, low_count,
                       summary, analysis_json
                FROM log_analysis
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                (page_size, offset),
            ).fetchall()
        except sqlite3.Error:
            return {"items": [], "total": 0, "page": page, "page_size": page_size}

    for row in rows:
        analysis: dict[str, Any] = {}
        try:
            analysis = json.loads(row["analysis_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            pass

        items.append({
            "id": int(row["id"]),
            "file_name": row["file_name"] or "",
            "created_at": row["created_at"] or "",
            "anomaly_count": int(row["anomaly_count"] or 0),
            "severity_distribution": {
                "critical": int(row["critical_count"] or 0),
                "high": int(row["high_count"] or 0),
                "medium": int(row["medium_count"] or 0),
                "low": int(row["low_count"] or 0),
            },
            "confidence": float(analysis.get("confidence") or 0.0),
            "reason": str(analysis.get("reason") or ""),
            "suggested_action": str(analysis.get("suggested_action") or ""),
            "risk_factors": list(analysis.get("risk_factors") or []),
            "anomaly_entries": list(analysis.get("anomaly_entries") or []),
            "summary": row["summary"] or "",
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


__all__ = (
    "latest",
    "history",
    "db_path",
    "db_exists",
)

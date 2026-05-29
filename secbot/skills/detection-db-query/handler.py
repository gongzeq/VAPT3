"""detection-db-query handler — read-only SQLite queries for reports.

Queries ``detection_results.db`` (phishing ``detection_results`` table and
log-analysis ``log_analysis`` table) and returns structured JSON the LLM can
consume directly for report generation. All actions are strictly read-only.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Iterator

from secbot.skills.types import InvalidSkillArg, SkillContext, SkillResult

# ---------------------------------------------------------------------------
# Database connection plumbing
# ---------------------------------------------------------------------------

_DEFAULT_DB_PATH = "/home/administrator/VAPT3/detection_results.db"
_CONNECT_TIMEOUT_S = 1.5

# Allowed actions — map 1:1 to the enum in input.schema.json
_VALID_ACTIONS = frozenset({
    "phishing_summary",
    "phishing_history",
    "phishing_stats",
    "phishing_trend",
    "phishing_top_senders",
    "log_latest",
    "log_stats",
    "db_schema",
    "sql_query",
})

# Confidence thresholds for the phishing filter labels.
_FILTER_MAP: dict[str, str] = {
    "phishing":   "ai_confidence >= 0.7",
    "suspicious": "ai_confidence >= 0.4 AND ai_confidence < 0.7",
    "normal":     "ai_confidence < 0.4",
    "all":        "1=1",
}

# SQL keywords that are unconditionally rejected in the sql_query action.
_FORBIDDEN_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|REPLACE|ATTACH|DETACH|PRAGMA)\b",
    re.IGNORECASE,
)


def _db_path() -> str:
    return os.environ.get("DETECTION_DB_PATH", _DEFAULT_DB_PATH)


def _db_exists() -> bool:
    return os.path.isfile(_db_path())


@contextmanager
def _connect() -> Iterator[sqlite3.Connection | None]:
    if not _db_exists():
        yield None
        return
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(_db_path(), timeout=_CONNECT_TIMEOUT_S)
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
# Response helpers
# ---------------------------------------------------------------------------

def _ok(action: str, data: Any, elapsed_ms: int) -> dict[str, Any]:
    return {"action": action, "ok": True, "data": data, "elapsed_ms": elapsed_ms}


def _err(action: str, msg: str, elapsed_ms: int) -> dict[str, Any]:
    return {"action": action, "ok": False, "error": msg, "elapsed_ms": elapsed_ms}


# ---------------------------------------------------------------------------
# Per-action query functions
# ---------------------------------------------------------------------------

def _phishing_summary() -> dict[str, Any]:
    """L1 card: today phishing + 7-day sparkline."""
    payload: dict[str, Any] = {
        "today_phishing": 0,
        "today_total": 0,
        "spark_7d": [],
    }
    with _connect() as conn:
        if conn is None:
            return payload

        today = datetime.now().date()
        start = today.strftime("%Y-%m-%d 00:00:00")
        end = (today + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")

        try:
            row = conn.execute(
                """SELECT COUNT(*),
                          COALESCE(SUM(CASE WHEN ai_confidence >= 0.7 THEN 1 ELSE 0 END), 0)
                   FROM detection_results
                   WHERE created_at >= ? AND created_at < ?""",
                (start, end),
            ).fetchone()
        except sqlite3.Error:
            return payload

        payload["today_total"] = int(row[0] or 0)
        payload["today_phishing"] = int(row[1] or 0)

        # 7-day sparkline
        try:
            spark_rows = conn.execute(
                """SELECT substr(created_at,1,10) AS day,
                          COALESCE(SUM(CASE WHEN ai_confidence>=0.7 THEN 1 ELSE 0 END),0) AS n
                   FROM detection_results
                   WHERE created_at >= datetime('now','-7 days','localtime')
                   GROUP BY day ORDER BY day ASC"""
            ).fetchall()
        except sqlite3.Error:
            spark_rows = []

        smap = {r["day"]: int(r["n"] or 0) for r in spark_rows}
        for offset in range(6, -1, -1):
            d = today - timedelta(days=offset)
            key = d.strftime("%Y-%m-%d")
            payload["spark_7d"].append({"date": key, "phishing": smap.get(key, 0)})

    return payload


def _phishing_history(
    page: int, page_size: int, search: str | None, filter_: str,
) -> dict[str, Any]:
    page = max(1, page)
    page_size = max(1, min(page_size, 500))
    offset = (page - 1) * page_size

    where = _FILTER_MAP.get(filter_, "1=1")
    args: list[Any] = []
    if search:
        s = f"%{search.strip()}%"
        where += " AND (sender LIKE ? OR subject LIKE ?)"
        args.extend([s, s])

    items: list[dict[str, Any]] = []
    total = 0
    with _connect() as conn:
        if conn is None:
            return {"items": [], "total": 0, "page": page, "page_size": page_size}
        try:
            total = int(
                conn.execute(
                    f"SELECT COUNT(*) FROM detection_results WHERE {where}",
                    tuple(args),
                ).fetchone()[0]
                or 0
            )
            rows = conn.execute(
                f"""SELECT id, content_hash, sender, subject,
                           ai_confidence, ai_reason, action, created_at,
                           processed_time_ms, risk_factors, rspamd_score,
                           final_score, rspamd_action
                    FROM detection_results
                    WHERE {where}
                    ORDER BY id DESC
                    LIMIT ? OFFSET ?""",
                (*args, page_size, offset),
            ).fetchall()
        except sqlite3.Error:
            return {"items": [], "total": 0, "page": page, "page_size": page_size}

    for row in rows:
        try:
            rf = json.loads(row["risk_factors"]) if row["risk_factors"] else []
        except Exception:
            rf = []
        items.append({
            "id": row["id"],
            "content_hash": row["content_hash"],
            "sender": row["sender"] or "",
            "subject": row["subject"] or "",
            "ai_confidence": float(row["ai_confidence"] or 0.0),
            "ai_reason": row["ai_reason"] or "",
            "action": row["action"] or "",
            "created_at": row["created_at"],
            "processed_time_ms": int(row["processed_time_ms"] or 0),
            "risk_factors": rf,
            "rspamd_score": float(row["rspamd_score"] or 0.0) if row["rspamd_score"] is not None else None,
            "final_score": float(row["final_score"] or 0.0) if row["final_score"] is not None else None,
            "rspamd_action": row["rspamd_action"] or "",
        })

    return {"items": items, "total": total, "page": page, "page_size": page_size}


def _phishing_stats() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "today_total": 0, "today_phishing": 0,
        "today_phishing_rate": 0.0, "avg_duration_ms": 0,
        "delta_total_pct": 0.0, "delta_phishing": 0,
    }
    with _connect() as conn:
        if conn is None:
            return payload
        today = datetime.now().date()
        today_start = today.strftime("%Y-%m-%d 00:00:00")
        today_end = (today + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")
        yesterday_start = (today - timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")

        try:
            t = conn.execute(
                """SELECT COUNT(*),
                          COALESCE(SUM(CASE WHEN ai_confidence >= 0.7 THEN 1 ELSE 0 END),0),
                          COALESCE(AVG(NULLIF(processed_time_ms,0)),0)
                   FROM detection_results WHERE created_at >= ? AND created_at < ?""",
                (today_start, today_end),
            ).fetchone()
            y = conn.execute(
                """SELECT COUNT(*),
                          COALESCE(SUM(CASE WHEN ai_confidence >= 0.7 THEN 1 ELSE 0 END),0)
                   FROM detection_results WHERE created_at >= ? AND created_at < ?""",
                (yesterday_start, today_start),
            ).fetchone()
        except sqlite3.Error:
            return payload

    tt = int(t[0] or 0); tp = int(t[1] or 0); ta = float(t[2] or 0)
    yt = int(y[0] or 0); yp = int(y[1] or 0)

    payload.update(
        today_total=tt, today_phishing=tp,
        today_phishing_rate=round(tp / tt, 4) if tt else 0.0,
        avg_duration_ms=int(round(ta)),
        delta_total_pct=round((tt - yt) / yt, 4) if yt else 0.0,
        delta_phishing=tp - yp,
    )
    return payload


def _phishing_trend(days: int) -> dict[str, Any]:
    days = max(1, min(days, 90))
    today = datetime.now().date()
    buckets = [
        {"date": (today - timedelta(days=offset)).strftime("%Y-%m-%d"),
         "phishing": 0, "suspicious": 0, "normal": 0, "rate": 0.0}
        for offset in range(days - 1, -1, -1)
    ]
    with _connect() as conn:
        if conn is None:
            return {"buckets": buckets}
        start = (today - timedelta(days=days - 1)).strftime("%Y-%m-%d 00:00:00")
        try:
            rows = conn.execute(
                """SELECT substr(created_at,1,10) AS day, COUNT(*) AS total,
                          SUM(CASE WHEN ai_confidence>=0.7 THEN 1 ELSE 0 END) AS phishing,
                          SUM(CASE WHEN ai_confidence>=0.4 AND ai_confidence<0.7 THEN 1 ELSE 0 END) AS suspicious,
                          SUM(CASE WHEN ai_confidence<0.4 THEN 1 ELSE 0 END) AS normal
                   FROM detection_results WHERE created_at >= ?
                   GROUP BY day""",
                (start,),
            ).fetchall()
        except sqlite3.Error:
            return {"buckets": buckets}

    by_day = {r["day"]: r for r in rows}
    for b in buckets:
        r = by_day.get(b["date"])
        if r is None:
            continue
        b["phishing"] = int(r["phishing"] or 0)
        b["suspicious"] = int(r["suspicious"] or 0)
        b["normal"] = int(r["normal"] or 0)
        total = int(r["total"] or 0)
        b["rate"] = round(b["phishing"] / total, 4) if total else 0.0
    return {"buckets": buckets}


def _phishing_top_senders(limit: int, days: int) -> dict[str, Any]:
    limit = max(1, min(limit, 500))
    days = max(1, min(days, 90))
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    items: list[dict[str, Any]] = []
    with _connect() as conn:
        if conn is None:
            return {"items": [], "limit": limit, "days": days}
        try:
            rows = conn.execute(
                """SELECT sender, COUNT(*) AS phishing,
                          MAX(ai_confidence) AS max_confidence,
                          MAX(created_at) AS last_seen
                   FROM detection_results
                   WHERE ai_confidence >= 0.7 AND created_at >= ?
                     AND sender IS NOT NULL AND sender <> ''
                   GROUP BY sender
                   ORDER BY phishing DESC, max_confidence DESC
                   LIMIT ?""",
                (cutoff, limit),
            ).fetchall()
        except sqlite3.Error:
            return {"items": [], "limit": limit, "days": days}

    for row in rows:
        items.append({
            "sender": row["sender"],
            "phishing": int(row["phishing"] or 0),
            "max_confidence": float(row["max_confidence"] or 0.0),
            "last_seen": row["last_seen"],
        })
    return {"items": items, "limit": limit, "days": days}


def _log_latest(limit: int) -> dict[str, Any]:
    limit = max(1, min(limit, 500))
    items: list[dict[str, Any]] = []
    with _connect() as conn:
        if conn is None:
            return {"items": [], "limit": limit}
        try:
            rows = conn.execute(
                """SELECT id, file_name, log_format, char_count,
                          analysis_timestamp, anomaly_count,
                          critical_count, high_count, medium_count, low_count,
                          summary, analysis_json, created_at
                   FROM log_analysis ORDER BY id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        except sqlite3.Error:
            return {"items": [], "limit": limit}

    for row in rows:
        analysis: dict[str, Any] = {}
        try:
            analysis = json.loads(row["analysis_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            pass
        items.append({
            "id": row["id"],
            "file_name": row["file_name"] or "",
            "log_format": row["log_format"] or "",
            "char_count": int(row["char_count"] or 0),
            "analysis_timestamp": row["analysis_timestamp"] or "",
            "anomaly_count": int(row["anomaly_count"] or 0),
            "severity": {
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
            "created_at": row["created_at"] or "",
        })
    return {"items": items, "limit": limit}


def _log_stats() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "total_analyses": 0,
        "total_anomalies": 0,
        "total_critical": 0,
        "total_high": 0,
        "total_medium": 0,
        "total_low": 0,
    }
    with _connect() as conn:
        if conn is None:
            return payload
        try:
            row = conn.execute(
                """SELECT COUNT(*) AS total,
                          COALESCE(SUM(anomaly_count),0) AS anomalies,
                          COALESCE(SUM(critical_count),0) AS critical,
                          COALESCE(SUM(high_count),0) AS high,
                          COALESCE(SUM(medium_count),0) AS medium,
                          COALESCE(SUM(low_count),0) AS low
                   FROM log_analysis"""
            ).fetchone()
        except sqlite3.Error:
            return payload

    if row:
        payload.update(
            total_analyses=int(row["total"] or 0),
            total_anomalies=int(row["anomalies"] or 0),
            total_critical=int(row["critical"] or 0),
            total_high=int(row["high"] or 0),
            total_medium=int(row["medium"] or 0),
            total_low=int(row["low"] or 0),
        )
    return payload


def _db_schema() -> dict[str, Any]:
    tables: dict[str, list[dict[str, Any]]] = {}
    with _connect() as conn:
        if conn is None:
            return {"tables": {}, "db_path": _db_path(), "db_exists": False}
        try:
            table_rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        except sqlite3.Error:
            return {"tables": {}, "db_path": _db_path(), "db_exists": _db_exists()}

        for tr in table_rows:
            tname = tr["name"]
            cols = conn.execute(f"PRAGMA table_info({tname})").fetchall()
            tables[tname] = [
                {"name": c["name"], "type": c["type"], "notnull": bool(c["notnull"])}
                for c in cols
            ]

    return {"tables": tables, "db_path": _db_path(), "db_exists": True}


def _sql_query(sql: str) -> dict[str, Any]:
    """Execute a user-supplied SELECT query with safety guards."""
    # Safety: reject any non-SELECT statement
    stripped = sql.strip()
    if _FORBIDDEN_SQL.search(stripped):
        return {"error": "Only SELECT queries are allowed (INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/PRAGMA rejected)"}

    if not re.match(r"^\s*SELECT\b", stripped, re.IGNORECASE):
        return {"error": "Query must start with SELECT"}

    # Limit to one statement
    if ";" in stripped.rstrip(";"):
        return {"error": "Only a single SQL statement is allowed"}

    rows_out: list[dict[str, Any]] = []
    with _connect() as conn:
        if conn is None:
            return {"error": "Database not found", "rows": [], "row_count": 0}
        try:
            cur = conn.execute(stripped)
            rows = cur.fetchall()
            rows_out = [dict(r) for r in rows]
            return {"rows": rows_out, "row_count": len(rows_out)}
        except sqlite3.Error as exc:
            return {"error": str(exc), "rows": [], "row_count": 0}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def run(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    """Dispatch to the appropriate query function based on ``action``."""
    action = str(args.get("action", "")).strip()

    if action not in _VALID_ACTIONS:
        raise InvalidSkillArg(
            f"Unknown action {action!r}. Valid: {sorted(_VALID_ACTIONS)}"
        )

    t0 = time.monotonic()

    try:
        if action == "phishing_summary":
            data = _phishing_summary()
        elif action == "phishing_history":
            data = _phishing_history(
                page=int(args.get("page", 1)),
                page_size=int(args.get("page_size", 50)),
                search=args.get("search"),
                filter_=str(args.get("filter", "all")),
            )
        elif action == "phishing_stats":
            data = _phishing_stats()
        elif action == "phishing_trend":
            data = _phishing_trend(days=int(args.get("days", 7)))
        elif action == "phishing_top_senders":
            data = _phishing_top_senders(
                limit=int(args.get("limit", 8)),
                days=int(args.get("days", 7)),
            )
        elif action == "log_latest":
            data = _log_latest(limit=int(args.get("limit", 20)))
        elif action == "log_stats":
            data = _log_stats()
        elif action == "db_schema":
            data = _db_schema()
        elif action == "sql_query":
            sql = str(args.get("sql", "")).strip()
            if not sql:
                raise InvalidSkillArg("'sql' is required for sql_query action")
            data = _sql_query(sql)
        else:
            # Should be unreachable due to the validation above.
            raise InvalidSkillArg(f"Unknown action {action!r}")
    except InvalidSkillArg:
        raise
    except Exception as exc:
        elapsed = int((time.monotonic() - t0) * 1000)
        return SkillResult(
            summary=_err(action, str(exc), elapsed),
        )

    elapsed = int((time.monotonic() - t0) * 1000)
    return SkillResult(summary=_ok(action, data, elapsed))

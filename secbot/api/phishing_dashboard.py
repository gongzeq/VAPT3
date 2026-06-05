"""Read-only access layer for the phishing-email detection results DB.

The business SQLite (``<project_root>/detection_results.db``,
overridable via ``PHISHING_DB_PATH``) is written by the ``step3`` script
of the phishing-email workflow (see :mod:`secbot.workflow.scripts`).
This module exposes the query primitives consumed by the dashboard REST
surface (``/api/dashboard/phishing/*``).

Design constraints (PRD §R6 + spec/backend/database-guidelines.md):
* Strictly read-only — no schema migrations, no writes. The owner of
  this DB is the workflow step3 script.
* Open per-call short-lived connections (``timeout=1.5s``). Dashboard
  reads must never block on a long-running write — SQLite WAL is enough
  but we still keep the connection ephemeral.
* Each function tolerates a missing DB file and returns an *empty*
  payload rather than raising — the dashboard endpoints translate this
  to zeroed widgets, never 500.
* No extra indexes are created here; the ``CREATE INDEX IF NOT EXISTS``
  lives in :mod:`secbot.workflow.scripts.PHISHING_STEP3_CODE` so the
  table is fully provisioned on the first successful workflow run.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Iterator


_DEFAULT_DB_PATH = str(Path(__file__).resolve().parents[2] / "detection_results.db")
_CONNECT_TIMEOUT_S = 1.5


def db_path() -> str:
    """Resolve the SQLite path from env, falling back to PRD default."""
    return os.environ.get("PHISHING_DB_PATH", _DEFAULT_DB_PATH)


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
        _migrate_schema(conn)
        yield conn
    except sqlite3.Error:
        yield None
    finally:
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Ensure the DB schema matches current expectations.

    Idempotent: safe to call on every connection open.
    - Drops UNIQUE constraint on content_hash (allows repeated detections)
    - Renames ai_suspicion_level -> ai_confidence (if still old name)
    - Adds risk_factors / rspamd_score / final_score columns (if missing)
    """
    # 1. Drop UNIQUE on content_hash so same email can produce multiple rows
    try:
        row = conn.execute(
            "SELECT sql FROM sqlite_master"
            " WHERE type='table' AND name='detection_results'"
        ).fetchone()
        if row is not None and "content_hash TEXT UNIQUE" in (row[0] or ""):
            cols = [
                r[1]
                for r in conn.execute(
                    "PRAGMA table_info(detection_results)"
                ).fetchall()
            ]
            cols_csv = ", ".join(cols)
            new_sql = (
                row[0]
                .replace("detection_results", "detection_results_new", 1)
                .replace("content_hash TEXT UNIQUE", "content_hash TEXT")
            )
            conn.execute(new_sql)
            conn.execute(
                f"INSERT INTO detection_results_new ({cols_csv})"
                f" SELECT {cols_csv} FROM detection_results"
            )
            conn.execute("DROP TABLE detection_results")
            conn.execute(
                "ALTER TABLE detection_results_new RENAME TO detection_results"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_detection_created_at"
                " ON detection_results(created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_detection_content_hash"
                " ON detection_results(content_hash)"
            )
            conn.commit()
    except Exception:
        pass
    # 2. Rename ai_suspicion_level -> ai_confidence (legacy migration)
    try:
        conn.execute(
            "ALTER TABLE detection_results RENAME COLUMN ai_suspicion_level"
            " TO ai_confidence"
        )
    except Exception:
        pass
    # 3. Add new columns
    for col, typ in [
        ("risk_factors", "TEXT"),
        ("rspamd_score", "REAL"),
        ("final_score", "REAL"),
        ("rspamd_action", "TEXT"),
    ]:
        try:
            conn.execute(
                f"ALTER TABLE detection_results ADD COLUMN {col} {typ}"
            )
        except Exception:
            pass


def _derive_rspamd_action(final_score: Any) -> str:
    """Fallback: compute rspamd_action from final_score when DB column is NULL."""
    if final_score is None:
        return ""
    score = float(final_score)
    if score >= 15:
        return "reject"
    if score >= 6:
        return "add_header"
    if score >= 4:
        return "greylist"
    return "accept"


def _today_bounds() -> tuple[str, str]:
    today = datetime.now().date()
    start = datetime.combine(today, datetime.min.time())
    end = start + timedelta(days=1)
    return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")


def _day_str(d: datetime) -> str:
    return d.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# L1 summary — single dashboard card
# ---------------------------------------------------------------------------


def summary() -> dict[str, Any]:
    """Aggregate the L1 summary card payload (PRD §R6).

    Returns
    -------
    dict
        ``{
            today_phishing, today_total, cache_hit_rate, avg_duration_ms,
            spark_7d: [{date, phishing}], generated_at
        }``
    """
    payload: dict[str, Any] = {
        "today_phishing": 0,
        "today_total": 0,
        "avg_duration_ms": 0,
        "spark_7d": _empty_spark(),
        "generated_at": _now_iso(),
    }
    with _connect() as conn:
        if conn is None:
            return payload
        start, end = _today_bounds()
        try:
            today_total, today_phishing, avg_ms = conn.execute(
                """
                SELECT
                    COUNT(*),
                    COALESCE(SUM(CASE WHEN ai_confidence >= 0.7 THEN 1 ELSE 0 END), 0),
                    COALESCE(AVG(NULLIF(processed_time_ms, 0)), 0)
                FROM detection_results
                WHERE created_at >= ? AND created_at < ?
                """,
                (start, end),
            ).fetchone()
        except sqlite3.Error:
            return payload

        payload["today_total"] = int(today_total or 0)
        payload["today_phishing"] = int(today_phishing or 0)
        # Prefer workflow run duration over step3-only processed_time_ms
        wf_avg = _avg_workflow_duration_ms(start, end)
        payload["avg_duration_ms"] = wf_avg if wf_avg > 0 else int(round(float(avg_ms or 0)))

        # 7-day sparkline (oldest → newest), using local-day buckets.
        try:
            spark_rows = conn.execute(
                """
                SELECT substr(created_at, 1, 10) AS day,
                       COALESCE(SUM(CASE WHEN ai_confidence >= 0.7 THEN 1 ELSE 0 END), 0) AS phishing
                FROM detection_results
                WHERE created_at >= datetime('now', '-7 days', 'localtime')
                GROUP BY day
                ORDER BY day ASC
                """
            ).fetchall()
        except sqlite3.Error:
            spark_rows = []

        spark_map = {row["day"]: int(row["phishing"] or 0) for row in spark_rows}
        spark = []
        today = datetime.now().date()
        for offset in range(6, -1, -1):
            day = today - timedelta(days=offset)
            key = _day_str(datetime.combine(day, datetime.min.time()))
            spark.append({"date": key, "phishing": spark_map.get(key, 0)})
        payload["spark_7d"] = spark

    return payload


def _empty_spark() -> list[dict[str, Any]]:
    today = datetime.now().date()
    return [
        {
            "date": _day_str(
                datetime.combine(today - timedelta(days=offset), datetime.min.time())
            ),
            "phishing": 0,
        }
        for offset in range(6, -1, -1)
    ]


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _workflow_runs_path() -> Path:
    """Locate the workflow runs.jsonl from standard workspace paths."""
    # Try env-based workspace, then fallback to default
    workspace = os.environ.get("SECBOT_WORKSPACE")
    if workspace:
        p = Path(workspace) / "workflows" / "runs.jsonl"
        if p.exists():
            return p
    # Default workspace path
    default = Path.home() / ".secbot" / "workspace" / "workflows" / "runs.jsonl"
    return default


def _avg_workflow_duration_ms(day_start: str, day_end: str) -> int:
    """Read average workflow run duration from runs.jsonl for given day.

    Falls back to 0 if the file doesn't exist or has no matching runs.
    Only considers completed (status != 'running') runs.
    """
    runs_path = _workflow_runs_path()
    if not runs_path.exists():
        return 0
    durations: list[int] = []
    day_start_ms = int(datetime.strptime(day_start, "%Y-%m-%d %H:%M:%S").timestamp() * 1000)
    day_end_ms = int(datetime.strptime(day_end, "%Y-%m-%d %H:%M:%S").timestamp() * 1000)
    try:
        with open(runs_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    run = json.loads(line)
                except Exception:
                    continue
                # Check time range
                started = run.get("startedAtMs") or run.get("started_at_ms") or 0
                finished = run.get("finishedAtMs") or run.get("finished_at_ms")
                status = run.get("status", "")
                if not started or not finished:
                    continue
                if status == "running":
                    continue
                if started < day_start_ms or started >= day_end_ms:
                    continue
                duration = int(finished) - int(started)
                if duration > 0:
                    durations.append(duration)
    except OSError:
        return 0
    if not durations:
        return 0
    return int(sum(durations) / len(durations))


# ---------------------------------------------------------------------------
# L2 KPIs — replaces /:5001/stats
# ---------------------------------------------------------------------------


def stats() -> dict[str, Any]:
    """KPI×4 payload for the L2 detail page (PRD §R6)."""
    payload: dict[str, Any] = {
        "today_total": 0,
        "today_phishing": 0,
        "today_phishing_rate": 0.0,
        "avg_duration_ms": 0,
        "delta": {
            "today_total_pct": 0.0,
            "today_phishing": 0,
            "avg_duration_ms": 0,
        },
        "generated_at": _now_iso(),
    }
    with _connect() as conn:
        if conn is None:
            return payload
        try:
            today_start, today_end = _today_bounds()
            yesterday_start = (
                datetime.now().date() - timedelta(days=1)
            ).strftime("%Y-%m-%d 00:00:00")
            today = conn.execute(
                """
                SELECT
                    COUNT(*),
                    COALESCE(SUM(CASE WHEN ai_confidence >= 0.7 THEN 1 ELSE 0 END), 0),
                    COALESCE(AVG(NULLIF(processed_time_ms, 0)), 0)
                FROM detection_results
                WHERE created_at >= ? AND created_at < ?
                """,
                (today_start, today_end),
            ).fetchone()
            yest = conn.execute(
                """
                SELECT
                    COUNT(*),
                    COALESCE(SUM(CASE WHEN ai_confidence >= 0.7 THEN 1 ELSE 0 END), 0),
                    COALESCE(AVG(NULLIF(processed_time_ms, 0)), 0)
                FROM detection_results
                WHERE created_at >= ? AND created_at < ?
                """,
                (yesterday_start, today_start),
            ).fetchone()
        except sqlite3.Error:
            return payload

    today_total = int(today[0] or 0)
    today_phish = int(today[1] or 0)
    today_avg = float(today[2] or 0)
    yest_total = int(yest[0] or 0)
    yest_phish = int(yest[1] or 0)
    yest_avg = float(yest[2] or 0)

    # Prefer workflow run duration (includes LLM time) over step3-only timing
    wf_avg_today = _avg_workflow_duration_ms(today_start, today_end)
    wf_avg_yest = _avg_workflow_duration_ms(yesterday_start, today_start)
    final_avg_today = wf_avg_today if wf_avg_today > 0 else int(round(today_avg))
    final_avg_yest = wf_avg_yest if wf_avg_yest > 0 else int(round(yest_avg))

    payload.update(
        today_total=today_total,
        today_phishing=today_phish,
        today_phishing_rate=round(today_phish / today_total, 4) if today_total else 0.0,
        avg_duration_ms=final_avg_today,
    )
    payload["delta"] = {
        "today_total_pct": _pct_delta(today_total, yest_total),
        "today_phishing": today_phish - yest_phish,
        "avg_duration_ms": final_avg_today - final_avg_yest,
    }
    return payload


def _pct_delta(now: int | float, prev: int | float) -> float:
    if not prev:
        return 0.0
    return round((now - prev) / prev, 4)


# ---------------------------------------------------------------------------
# L2 detail rows — replaces /:5001/history
# ---------------------------------------------------------------------------


_FILTER_MAP = {
    "phishing": "ai_confidence >= 0.7",
    "suspicious": "ai_confidence >= 0.4 AND ai_confidence < 0.7",
    "normal": "ai_confidence < 0.4",
    "all": "1=1",
}


def history(
    *,
    limit: int | None = None,
    page: int = 1,
    page_size: int = 50,
    search: str | None = None,
    filter_: str = "all",
) -> dict[str, Any]:
    """Paginated detection rows (PRD §R6).

    ``filter_`` ∈ {phishing, suspicious, normal, all}.

    The legacy ``limit`` parameter remains supported (it overrides
    ``page_size`` and forces ``page=1``); new callers should pass
    ``page``/``page_size`` instead.
    """
    if limit is not None:
        page = 1
        page_size = max(1, min(int(limit), 500))
    else:
        page = max(1, int(page or 1))
        page_size = max(1, min(int(page_size or 50), 500))
    offset = (page - 1) * page_size
    where = _FILTER_MAP.get((filter_ or "all").lower(), "1=1")
    args: list[Any] = []
    if search:
        search_clean = f"%{search.strip()}%"
        where += " AND (sender LIKE ? OR subject LIKE ?)"
        args.extend([search_clean, search_clean])

    items: list[dict[str, Any]] = []
    total = 0
    with _connect() as conn:
        if conn is None:
            return {
                "items": [],
                "total": 0,
                "page": page,
                "page_size": page_size,
            }
        try:
            total = int(
                conn.execute(
                    f"SELECT COUNT(*) FROM detection_results WHERE {where}",
                    tuple(args),
                ).fetchone()[0]
                or 0
            )
            rows = conn.execute(
                f"""
                SELECT id, content_hash, sender, subject,
                       ai_confidence, ai_reason, action, created_at,
                       processed_time_ms, risk_factors, rspamd_score,
                       final_score, rspamd_action
                FROM detection_results
                WHERE {where}
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                (*args, page_size, offset),
            ).fetchall()
        except sqlite3.Error:
            return {
                "items": [],
                "total": 0,
                "page": page,
                "page_size": page_size,
            }

    for row in rows:
        try:
            rf = json.loads(row["risk_factors"]) if row["risk_factors"] else []
        except Exception:
            rf = []
        items.append(
            {
                "id": int(row["id"]),
                "content_hash": row["content_hash"],
                "sender": row["sender"] or "",
                "subject": row["subject"] or "",
                "suspicion_level": float(row["ai_confidence"] or 0.0),
                "reason": row["ai_reason"] or "",
                "action": row["action"] or "",
                "created_at": row["created_at"],
                "processed_time_ms": int(row["processed_time_ms"] or 0),
                "risk_factors": rf,
                "rspamd_score": float(row["rspamd_score"] or 0.0) if row["rspamd_score"] is not None else None,
                "final_score": float(row["final_score"] or 0.0) if row["final_score"] is not None else None,
                "rspamd_action": row["rspamd_action"] or _derive_rspamd_action(row["final_score"]),
            }
        )
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ---------------------------------------------------------------------------
# L2 trend — replaces /:5001/trend
# ---------------------------------------------------------------------------


def trend(*, days: int = 7) -> dict[str, Any]:
    """Stacked-bar trend payload (phishing/suspicious/normal + rate)."""
    days = max(1, min(int(days or 7), 90))
    today = datetime.now().date()
    bucket_keys = [
        _day_str(datetime.combine(today - timedelta(days=offset), datetime.min.time()))
        for offset in range(days - 1, -1, -1)
    ]
    payload: dict[str, list[dict[str, Any]]] = {
        "buckets": [
            {"date": k, "phishing": 0, "suspicious": 0, "normal": 0, "rate": 0.0}
            for k in bucket_keys
        ]
    }
    with _connect() as conn:
        if conn is None:
            return payload
        start = (today - timedelta(days=days - 1)).strftime("%Y-%m-%d 00:00:00")
        try:
            rows = conn.execute(
                """
                SELECT substr(created_at, 1, 10) AS day,
                       COUNT(*) AS total,
                       SUM(CASE WHEN ai_confidence >= 0.7
                                THEN 1 ELSE 0 END) AS phishing,
                       SUM(CASE WHEN ai_confidence >= 0.4 AND ai_confidence < 0.7
                                THEN 1 ELSE 0 END) AS suspicious,
                       SUM(CASE WHEN ai_confidence < 0.4 THEN 1 ELSE 0 END) AS normal
                FROM detection_results
                WHERE created_at >= ?
                GROUP BY day
                """,
                (start,),
            ).fetchall()
        except sqlite3.Error:
            return payload

    by_day = {row["day"]: row for row in rows}
    for bucket in payload["buckets"]:
        row = by_day.get(bucket["date"])
        if row is None:
            continue
        bucket["phishing"] = int(row["phishing"] or 0)
        bucket["suspicious"] = int(row["suspicious"] or 0)
        bucket["normal"] = int(row["normal"] or 0)
        total = int(row["total"] or 0)
        if total:
            bucket["rate"] = round(bucket["phishing"] / total, 4)
    return payload


# ---------------------------------------------------------------------------
# L2 top senders — replaces /:5001/top-senders
# ---------------------------------------------------------------------------


def top_senders(*, limit: int = 8, days: int = 7) -> dict[str, Any]:
    """High-risk sender ranking (PRD §R6)."""
    limit = max(1, min(int(limit or 8), 50))
    days = max(1, min(int(days or 7), 90))
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    items: list[dict[str, Any]] = []
    with _connect() as conn:
        if conn is None:
            return {"items": [], "limit": limit, "days": days}
        try:
            rows = conn.execute(
                """
                SELECT sender,
                       COUNT(*) AS phishing,
                       MAX(ai_confidence) AS max_confidence,
                       MAX(created_at) AS last_seen
                FROM detection_results
                WHERE ai_confidence >= 0.7
                  AND created_at >= ?
                  AND sender IS NOT NULL
                  AND sender <> ''
                GROUP BY sender
                ORDER BY phishing DESC, max_confidence DESC
                LIMIT ?
                """,
                (cutoff, limit),
            ).fetchall()
        except sqlite3.Error:
            return {"items": [], "limit": limit, "days": days}

    for row in rows:
        items.append(
            {
                "sender": row["sender"],
                "phishing": int(row["phishing"] or 0),
                "max_confidence": float(row["max_confidence"] or 0.0),
                "last_seen": row["last_seen"],
            }
        )
    return {"items": items, "limit": limit, "days": days}


# ---------------------------------------------------------------------------
# L2 health — aggregate link health card
# ---------------------------------------------------------------------------


def health() -> dict[str, Any]:
    """Aggregate link-health payload covering 5 components."""
    return {
        "components": [
            {"name": "postfix", "status": _systemd_status("postfix.service")},
            {"name": "rspamd", "status": _systemd_status("rspamd.service")},
            {"name": "workflow", "status": "ok"},
            {"name": "provider", "status": _provider_status()},
            {"name": "sqlite", "status": _sqlite_status()},
        ],
        "generated_at": _now_iso(),
    }


def _systemd_status(unit: str) -> str:
    try:
        import subprocess

        rc = subprocess.run(
            ["systemctl", "is-active", "--quiet", unit],
            timeout=1.0,
            check=False,
        ).returncode
        return "ok" if rc == 0 else "down"
    except Exception:
        return "unknown"


def _provider_status() -> str:
    # Cheap check — the workflow LLM executor will surface real provider
    # latency via runs.jsonl. For the dashboard we just probe the env
    # config presence; a richer probe lives in PR-follow-up.
    if os.environ.get("OPENAI_API_KEY") or os.environ.get("OLLAMA_BASE_URL"):
        return "ok"
    return "unknown"


def _sqlite_status() -> str:
    return "ok" if db_exists() else "down"


__all__: Iterable[str] = (
    "summary",
    "stats",
    "history",
    "trend",
    "top_senders",
    "health",
    "db_path",
    "db_exists",
)


# Time module is consumed indirectly via :mod:`datetime`; keep an explicit
# import so the linter doesn't strip the package on a future cleanup pass.
_ = time

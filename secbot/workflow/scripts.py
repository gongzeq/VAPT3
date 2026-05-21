"""Inline Python snippets used by the phishing-email workflow template.

Why a separate module?
* The snippets are large, multi-line strings that we don't want to inline
  in :mod:`secbot.workflow.templates` (loses syntax highlighting, makes
  the template harder to diff).
* Storing them as ``str`` constants here lets us import + unit-test the
  snippets in isolation by ``exec(...)``-ing them with a fixture stdin.

The runtime contract for each snippet:

* Reads a single JSON object from stdin (the workflow runner pipes the
  template's interpolated ``stdin`` through ``python3 -``).
* Writes ONE flat JSON object to stdout — every consumer (the runner, the
  Lua plugin) parses ``stepResults.<step>.output.stdout``.
* On any internal failure: still emit a JSON object with ``error`` set so
  the next step has something to operate on. The script must NEVER print
  Python tracebacks to stdout; tracebacks go to stderr only.
* No third-party imports. ``sqlite3`` is pulled lazily and
  failures degrade gracefully (the cache and write-back layers are best
  effort — the workflow keeps running without them).

Spec: PRD §R1, §R5 (容错策略), §Technical Notes (ScriptExecutor 60s 上限).
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# step1 — 特征提取 + SQLite 去重 + 脱敏
# ---------------------------------------------------------------------------


PHISHING_STEP1_CODE = r'''
import email
import email.policy
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import traceback
from urllib.parse import urlparse


_DB_PATH = os.environ.get(
    "PHISHING_DB_PATH",
    "/home/administrator/VAPT3/detection_results.db",
)


def _lookup_sqlite_cache(chash: str) -> dict | None:
    """Return the most recent LLM result for *chash* from the local SQLite DB.

    Only genuine LLM results are used (reason not starting with
    "LLM skipped").  Returns None when not found or on any DB error.
    """
    if not os.path.isfile(_DB_PATH):
        return None
    try:
        conn = sqlite3.connect(_DB_PATH, timeout=1.0)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT ai_confidence, ai_reason, action, risk_factors
            FROM   detection_results
            WHERE  content_hash = ?
              AND  ai_confidence IS NOT NULL
              AND  (ai_reason IS NULL OR ai_reason NOT LIKE 'LLM skipped%')
            ORDER  BY id DESC
            LIMIT  1
            """,
            (chash,),
        ).fetchone()
        conn.close()
        if row is None:
            return None
        import json as _json
        try:
            rf = _json.loads(row["risk_factors"]) if row["risk_factors"] else []
        except Exception:
            rf = []
        return {
            "confidence": float(row["ai_confidence"] or 0.0),
            "reason": str(row["ai_reason"] or "(cached)"),
            "suggested_action": str(row["action"] or ""),
            "risk_factors": rf,
        }
    except Exception:
        return None


def _extract_plain_text(raw: str) -> str:
    """Extract plain text from raw MIME email.

    Uses Python email module to correctly parse multipart structure
    and extract text/plain (preferred) or stripped text/html.
    Falls back to regex-based HTML stripping if MIME parsing fails.
    """
    try:
        msg = email.message_from_string(raw, policy=email.policy.default)
        # Prefer text/plain, fall back to text/html
        body_part = msg.get_body(preferencelist=("plain", "html"))
        if body_part:
            content = body_part.get_content()
            if body_part.get_content_type() == "text/html":
                content = re.sub(r"<[^>]+>", " ", content)
            return content
        # Walk parts as fallback
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                return part.get_content()
            if ct == "text/html":
                return re.sub(r"<[^>]+>", " ", part.get_content())
    except Exception:
        pass
    # Last resort: strip HTML from raw input
    return re.sub(r"<[^>]+>", " ", raw)


def _content_hash(sender: str, subject: str, body: str) -> str:
    h = hashlib.sha256()
    h.update((sender or "").strip().lower().encode("utf-8", "replace"))
    h.update(b"|")
    h.update((subject or "").strip().encode("utf-8", "replace"))
    h.update(b"|")
    # Extract real text content from MIME body, then normalize.
    plain = _extract_plain_text(body or "")
    normalized = re.sub(r"\s+", " ", plain).strip().lower()
    h.update(normalized.encode("utf-8", "replace"))
    return h.hexdigest()


_SUSP_TLD = {"zip", "top", "xyz", "click", "link", "loan", "country"}
_LOOKALIKE_TOKENS = (
    "paypa1", "app1e", "m1crosoft", "gma1l", "amaz0n", "gith0b", "secur",
)


def _suspicious_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return True
    tld = host.rsplit(".", 1)[-1] if "." in host else ""
    if tld in _SUSP_TLD:
        return True
    if any(tok in host for tok in _LOOKALIKE_TOKENS):
        return True
    if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", host):
        return True
    return False


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.write("\n")


def main() -> int:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw or "{}")
    except Exception as exc:
        _emit({
            "error": f"step1.input_parse: {exc}",
            "cache_hit": False,
            "features": {},
        })
        return 0

    sender = str(data.get("sender") or "")
    subject = str(data.get("subject") or "")
    body = str(data.get("body") or "")
    rspamd_score_raw = str(data.get("rspamd_score") or "0")
    urls_in = data.get("urls") or []
    if isinstance(urls_in, str):
        try:
            urls_in = json.loads(urls_in or "[]")
        except Exception:
            urls_in = []
    if not isinstance(urls_in, list):
        urls_in = []
    urls = [str(u) for u in urls_in[:50]]

    sender_local, _, sender_domain = sender.partition("@")
    body_excerpt = re.sub(r"\s+", " ", body).strip()[:600]
    suspicious_domains = sorted({
        urlparse(u).hostname or ""
        for u in urls
        if _suspicious_url(u)
    } - {""})

    chash = _content_hash(sender, subject, body)

    cache_hit = False
    cached_result = None

    # SQLite-based cache lookup (always available, no extra deps)
    cached_result = _lookup_sqlite_cache(chash)
    if cached_result is not None:
        cache_hit = True

    try:
        rspamd_score = float(rspamd_score_raw)
    except Exception:
        rspamd_score = 0.0

    _emit({
        "cache_hit": cache_hit,
        "cached_result": cached_result,
        "content_hash": chash,
        "rspamd_score": rspamd_score,
        "workflow_start_ms": int(time.time() * 1000),
        "features": {
            "sender_full": sender,
            "sender_local": sender_local,
            "sender_domain": sender_domain,
            "subject": subject[:200],
            "body_excerpt": body_excerpt,
            "url_count": len(urls),
            "suspicious_domains": suspicious_domains[:10],
            "recipient": str(data.get("recipient") or ""),
        },
    })
    return 0


try:
    sys.exit(main())
except Exception:
    sys.stderr.write(traceback.format_exc())
    # Defensive last-resort payload so step3 always has structure to read.
    sys.stdout.write(json.dumps({
        "error": "step1.unhandled",
        "cache_hit": False,
        "features": {},
    }, ensure_ascii=False) + "\n")
    sys.exit(0)
'''


# ---------------------------------------------------------------------------
# step3 — 聚合 + add_score 计算 + 回写业务 SQLite
# ---------------------------------------------------------------------------


PHISHING_STEP3_CODE = r'''
import json
import os
import sqlite3
import sys
import time
import traceback


_DB_PATH = os.environ.get(
    "PHISHING_DB_PATH",
    "/home/administrator/VAPT3/detection_results.db",
)


def _migrate_drop_unique(conn: sqlite3.Connection) -> None:
    """Drop UNIQUE on content_hash so repeated detections all get stored.

    SQLite has no DROP CONSTRAINT; the only way is to recreate the table.
    Safe to call repeatedly — checks the schema string first.
    """
    try:
        row = conn.execute(
            "SELECT sql FROM sqlite_master"
            " WHERE type='table' AND name='detection_results'"
        ).fetchone()
        if row is None or "content_hash TEXT UNIQUE" not in (row[0] or ""):
            return  # nothing to do
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
    except Exception as exc:
        sys.stderr.write(f"[step3] migrate_drop_unique failed: {exc}\n")


def _ensure_table(conn: sqlite3.Connection) -> None:
    # Drop UNIQUE on content_hash first so the following CREATE TABLE
    # definition (content_hash TEXT NOT NULL, no UNIQUE) is the canonical one.
    _migrate_drop_unique(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS detection_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_hash TEXT NOT NULL,
            sender TEXT,
            subject TEXT,
            ai_confidence REAL,
            ai_reason TEXT,
            action TEXT,
            created_at TEXT,
            processed_time_ms INTEGER,
            risk_factors TEXT,
            rspamd_score REAL,
            final_score REAL,
            rspamd_action TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_detection_created_at "
        "ON detection_results(created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_detection_content_hash "
        "ON detection_results(content_hash)"
    )
    # --- Migrations for existing tables ---
    # Add new columns
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
    # Rename ai_suspicion_level -> ai_confidence (legacy migration)
    try:
        conn.execute(
            "ALTER TABLE detection_results RENAME COLUMN ai_suspicion_level"
            " TO ai_confidence"
        )
    except Exception:
        pass


def _persist_sqlite(row: dict) -> bool:
    db_dir = os.path.dirname(_DB_PATH)
    if db_dir:
        try:
            os.makedirs(db_dir, exist_ok=True)
        except Exception:
            pass
    try:
        conn = sqlite3.connect(_DB_PATH, timeout=2.0)
    except Exception as exc:
        sys.stderr.write(f"[step3] sqlite connect failed: {exc}\n")
        return False
    try:
        _ensure_table(conn)
        conn.execute(
            """
            INSERT INTO detection_results
                (content_hash, sender, subject, ai_confidence,
                 ai_reason, action, created_at, processed_time_ms,
                 risk_factors, rspamd_score, final_score, rspamd_action)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row.get("content_hash"),
                row.get("sender"),
                row.get("subject"),
                float(row.get("confidence") or 0.0),
                row.get("reason"),
                row.get("suggested_action"),
                row.get("created_at"),
                int(row.get("processed_time_ms") or 0),
                json.dumps(row.get("risk_factors") or [], ensure_ascii=False),
                float(row.get("rspamd_score") or 0.0) if row.get("rspamd_score") is not None else None,
                float(row.get("final_score") or 0.0) if row.get("final_score") is not None else None,
                row.get("rspamd_action") or "",
            ),
        )
        conn.commit()
        return True
    except Exception as exc:
        sys.stderr.write(f"[step3] sqlite persist failed: {exc}\n")
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _add_score_for(suspicion_level: float) -> float:
    """Map LLM suspicion level to rspamd score delta.

    Formula:  add_score = suspicion_level × 8.0

    Suspicion level (0.0–1.0) represents how suspicious the email is.
    A fixed multiplier keeps the scoring simple and predictable:
      - 1.0 → 8.0 (max addition)
      - 0.6 → 4.8
      - 0.2 → 1.6
      - 0.0 → 0.0
    """
    return round(suspicion_level * 8.0, 2)


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.write("\n")


def _rspamd_action(score: float) -> str:
    """Derive the rspamd final action from total score.

    Thresholds (from rspamadm configdump):
      >= 15  → reject (拒绝投递，直接退信)
      >=  6  → add_header (投递，标记为 spam)
      >=  4  → greylist (临时拒绝，要求重试)
      <   4  → accept (正常投递)
    """
    if score >= 15:
        return "reject"
    if score >= 6:
        return "add_header"
    if score >= 4:
        return "greylist"
    return "accept"


def main() -> int:
    started = time.time()
    raw = sys.stdin.read()
    try:
        data = json.loads(raw or "{}")
    except Exception as exc:
        _emit({
            "error": f"step3.input_parse: {exc}",
            "add_score": 0.0,
            "confidence": 0.0,
            "reason": "step3 input parse failed; defaulting add_score=0",
            "suggested_action": "放行",
            "risk_factors": [],
        })
        return 0

    step1 = data.get("step1") or {}
    step2 = data.get("step2") or {}
    rspamd_score = data.get("rspamd_score")

    features = step1.get("features") or {}
    chash = step1.get("content_hash") or ""
    sender = features.get("sender_full") or ""
    subject = features.get("subject") or ""
    # Use workflow_start_ms from step1 to calculate total processing time
    workflow_start_ms = step1.get("workflow_start_ms") or 0

    cache_hit = bool(step1.get("cache_hit"))
    cached = step1.get("cached_result") or {}

    if cache_hit and cached:
        # Trust the cached judgement verbatim; recompute add_score so
        # tuning the matrix takes effect on next read without bumping TTL.
        confidence = float(cached.get("confidence") or 0.0)
        reason = str(cached.get("reason") or "(cached)")
        suggested_action = str(cached.get("suggested_action") or "")
        risk_factors = list(cached.get("risk_factors") or [])
        add_score = float(cached.get("add_score", _add_score_for(confidence)))
    else:
        # Accept two shapes for ``step2``:
        # 1. The full LlmExecutor wrapper ``{content, parsed, ...}`` --
        #    business JSON nested under ``.parsed``.
        # 2. The already-unwrapped business dict (``{confidence,
        #    reason, ...}`` at the top level), which is what the
        #    current phishing template's stdin produces by interpolating
        #    the step2 parsed result directly.
        # NOTE: do NOT write the ``$``+``{...}`` placeholder syntax here --
        # this comment lives inside ``args.code`` which the runner runs
        # through ``interpolate`` before exec, so the literal would be
        # substituted with the real (URL-containing) JSON and trip the
        # SSRF guard in ``ExecTool._guard_command``.
        # Detection is purely structural: if ``parsed`` is a dict, use
        # it; else if ``step2`` itself has the business keys, use it.
        parsed: dict | None = None
        if isinstance(step2, dict):
            inner = step2.get("parsed")
            if isinstance(inner, dict):
                parsed = inner
            elif "confidence" in step2 or "reason" in step2:
                parsed = step2
        if not isinstance(parsed, dict):
            # LLM was skipped (rspamd_score outside [4,10]) or errored.
            # Default to放行 with a clear reason.
            early_now_ms = int(time.time() * 1000)
            early_processed = (early_now_ms - workflow_start_ms) if workflow_start_ms > 0 else int((time.time() - started) * 1000)
            early_created_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            early_result = {
                "add_score": 0.0,
                "confidence": 0.0,
                "reason": "LLM skipped or unavailable; default add_score=0",
                "suggested_action": "放行",
                "risk_factors": [],
                "content_hash": chash,
                "sender": sender,
                "subject": subject,
                "rspamd_score": rspamd_score,
                "final_score": float(rspamd_score or 0.0),
                "rspamd_action": _rspamd_action(float(rspamd_score or 0.0)),
                "processed_time_ms": early_processed,
                "created_at": early_created_at,
            }
            # Persist to SQLite even for LLM-skipped path
            if chash:
                _persist_sqlite(early_result)
            _emit(early_result)
            return 0

        confidence = float(parsed.get("confidence") or 0.0)
        reason = str(parsed.get("reason") or "")
        suggested_action = str(parsed.get("suggested_action") or "")
        risk_factors = list(parsed.get("risk_factors") or [])
        add_score = _add_score_for(confidence)

    # Calculate total workflow processing time (from step1 start to now)
    now_ms = int(time.time() * 1000)
    if workflow_start_ms > 0:
        processed_ms = now_ms - workflow_start_ms
    else:
        processed_ms = int((time.time() - started) * 1000)
    created_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

    rspamd_score_f = float(rspamd_score or 0.0)
    final_score = round(rspamd_score_f + float(add_score), 2)
    rspamd_action = _rspamd_action(final_score)

    result = {
        "add_score": float(add_score),
        "confidence": float(confidence),
        "reason": reason,
        "suggested_action": suggested_action,
        "risk_factors": risk_factors,
        "content_hash": chash,
        "sender": sender,
        "subject": subject,
        "rspamd_score": rspamd_score_f,
        "final_score": final_score,
        "rspamd_action": rspamd_action,
        "processed_time_ms": processed_ms,
        "created_at": created_at,
    }

    # Always persist to SQLite for dashboard visibility.
    if chash:
        _persist_sqlite(result)

    _emit(result)
    return 0


try:
    sys.exit(main())
except Exception:
    sys.stderr.write(traceback.format_exc())
    sys.stdout.write(json.dumps({
        "error": "step3.unhandled",
        "add_score": 0.0,
        "confidence": 0.0,
        "reason": "step3 unhandled exception; defaulting add_score=0",
        "suggested_action": "放行",
        "risk_factors": [],
    }, ensure_ascii=False) + "\n")
    sys.exit(0)
'''


__all__ = ["PHISHING_STEP1_CODE", "PHISHING_STEP3_CODE"]

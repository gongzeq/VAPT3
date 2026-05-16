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
* No third-party imports. ``redis`` / ``sqlite3`` are pulled lazily and
  failures degrade gracefully (the cache and write-back layers are best
  effort — the workflow keeps running without them).

Spec: PRD §R1, §R5 (容错策略), §Technical Notes (ScriptExecutor 60s 上限).
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# step1 — 特征提取 + Redis 7 天去重 + 脱敏
# ---------------------------------------------------------------------------


PHISHING_STEP1_CODE = r'''
import hashlib
import json
import os
import re
import sys
import traceback
from urllib.parse import urlparse


def _safe_load_redis():
    try:
        import redis  # type: ignore[import-not-found]
    except Exception:
        return None
    try:
        return redis.Redis(
            host=os.environ.get("REDIS_HOST", "127.0.0.1"),
            port=int(os.environ.get("REDIS_PORT", "6379")),
            db=int(os.environ.get("REDIS_DB", "0")),
            socket_timeout=2.0,
            socket_connect_timeout=2.0,
            decode_responses=True,
        )
    except Exception:
        return None


def _content_hash(sender: str, subject: str, body: str) -> str:
    h = hashlib.sha256()
    h.update((sender or "").strip().lower().encode("utf-8", "replace"))
    h.update(b"|")
    h.update((subject or "").strip().encode("utf-8", "replace"))
    h.update(b"|")
    h.update((body or "").strip().encode("utf-8", "replace"))
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
    cache_key = f"ai:result:{chash}"

    cache_hit = False
    cached_result = None
    redis_ok = False
    rds = _safe_load_redis()
    if rds is not None:
        try:
            raw_cached = rds.get(cache_key)
            redis_ok = True
            if raw_cached:
                try:
                    cached_result = json.loads(raw_cached)
                    cache_hit = True
                except Exception:
                    cached_result = None
        except Exception:
            redis_ok = False

    try:
        rspamd_score = float(rspamd_score_raw)
    except Exception:
        rspamd_score = 0.0

    _emit({
        "cache_hit": cache_hit,
        "cached_result": cached_result,
        "redis_ok": redis_ok,
        "content_hash": chash,
        "rspamd_score": rspamd_score,
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
# step3 — 聚合 + add_score 计算 + 回写 Redis & 业务 SQLite
# ---------------------------------------------------------------------------


PHISHING_STEP3_CODE = r'''
import json
import os
import sqlite3
import sys
import time
import traceback


_CACHE_TTL_SEC = int(os.environ.get("PHISHING_CACHE_TTL", "604800"))  # 7 days
_DB_PATH = os.environ.get(
    "PHISHING_DB_PATH",
    "/home/administrator/VAPT3/detection_results.db",
)


def _safe_load_redis():
    try:
        import redis  # type: ignore[import-not-found]
    except Exception:
        return None
    try:
        return redis.Redis(
            host=os.environ.get("REDIS_HOST", "127.0.0.1"),
            port=int(os.environ.get("REDIS_PORT", "6379")),
            db=int(os.environ.get("REDIS_DB", "0")),
            socket_timeout=2.0,
            socket_connect_timeout=2.0,
            decode_responses=True,
        )
    except Exception:
        return None


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS detection_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_hash TEXT NOT NULL,
            sender TEXT,
            subject TEXT,
            ai_is_phishing INTEGER,
            ai_confidence REAL,
            ai_reason TEXT,
            action TEXT,
            created_at TEXT,
            processed_time_ms INTEGER
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


def _persist_sqlite(row: dict) -> bool:
    try:
        os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    except Exception:
        pass
    try:
        conn = sqlite3.connect(_DB_PATH, timeout=2.0)
    except Exception:
        return False
    try:
        _ensure_table(conn)
        conn.execute(
            """
            INSERT INTO detection_results
                (content_hash, sender, subject, ai_is_phishing, ai_confidence,
                 ai_reason, action, created_at, processed_time_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row.get("content_hash"),
                row.get("sender"),
                row.get("subject"),
                1 if row.get("is_phishing") else 0,
                float(row.get("confidence") or 0.0),
                row.get("reason"),
                row.get("suggested_action"),
                row.get("created_at"),
                int(row.get("processed_time_ms") or 0),
            ),
        )
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _add_score_for(
    is_phishing: bool, confidence: float, risk_level: str
) -> float:
    """Map LLM judgement to rspamd score delta.

    Mirrors `ai_detector.py`'s decision matrix:
      high risk    → 5.0
      medium risk  → 2.5
      low risk     → 0.5
      safe / unknown → 0.0
    Cache hits use the cached `add_score` directly upstream.
    """
    rl = (risk_level or "").lower()
    if not is_phishing:
        return 0.0
    if rl == "high" or confidence >= 0.85:
        return 5.0
    if rl == "medium" or confidence >= 0.6:
        return 2.5
    if rl == "low" or confidence >= 0.4:
        return 0.5
    return 0.0


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.write("\n")


def main() -> int:
    started = time.time()
    raw = sys.stdin.read()
    try:
        data = json.loads(raw or "{}")
    except Exception as exc:
        _emit({
            "error": f"step3.input_parse: {exc}",
            "add_score": 0.0,
            "is_phishing": False,
            "confidence": 0.0,
            "reason": "step3 input parse failed; defaulting add_score=0",
            "suggested_action": "放行",
            "from_cache": False,
        })
        return 0

    step1 = data.get("step1") or {}
    step2 = data.get("step2") or {}
    rspamd_score = data.get("rspamd_score")

    features = step1.get("features") or {}
    chash = step1.get("content_hash") or ""
    sender = features.get("sender_full") or ""
    subject = features.get("subject") or ""

    cache_hit = bool(step1.get("cache_hit"))
    cached = step1.get("cached_result") or {}

    if cache_hit and cached:
        # Trust the cached judgement verbatim; recompute add_score so
        # tuning the matrix takes effect on next read without bumping TTL.
        is_phishing = bool(cached.get("is_phishing"))
        confidence = float(cached.get("confidence") or 0.0)
        risk_level = str(cached.get("risk_level") or "")
        reason = str(cached.get("reason") or "(cached)")
        suggested_action = str(cached.get("suggested_action") or "")
        risk_factors = list(cached.get("risk_factors") or [])
        add_score = float(cached.get("add_score", _add_score_for(
            is_phishing, confidence, risk_level
        )))
        from_cache = True
    else:
        # Accept two shapes for ``step2``:
        # 1. The full LlmExecutor wrapper ``{content, parsed, ...}`` --
        #    business JSON nested under ``.parsed``.
        # 2. The already-unwrapped business dict (``{is_phishing,
        #    confidence, ...}`` at the top level), which is what the
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
            elif "is_phishing" in step2 or "risk_level" in step2:
                parsed = step2
        if not isinstance(parsed, dict):
            # LLM was skipped (rspamd_score outside [4,10]) or errored.
            # Default to放行 with a clear reason.
            _emit({
                "add_score": 0.0,
                "is_phishing": False,
                "confidence": 0.0,
                "risk_level": "safe",
                "reason": "LLM skipped or unavailable; default add_score=0",
                "suggested_action": "放行",
                "risk_factors": [],
                "from_cache": False,
                "content_hash": chash,
                "sender": sender,
                "subject": subject,
                "rspamd_score": rspamd_score,
                "processed_time_ms": int((time.time() - started) * 1000),
            })
            return 0

        is_phishing = bool(parsed.get("is_phishing"))
        confidence = float(parsed.get("confidence") or 0.0)
        risk_level = str(parsed.get("risk_level") or "")
        reason = str(parsed.get("reason") or "")
        suggested_action = str(parsed.get("suggested_action") or "")
        risk_factors = list(parsed.get("risk_factors") or [])
        add_score = _add_score_for(is_phishing, confidence, risk_level)
        from_cache = False

    processed_ms = int((time.time() - started) * 1000)
    created_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

    result = {
        "add_score": float(add_score),
        "is_phishing": bool(is_phishing),
        "confidence": float(confidence),
        "risk_level": risk_level,
        "reason": reason,
        "suggested_action": suggested_action,
        "risk_factors": risk_factors,
        "from_cache": from_cache,
        "content_hash": chash,
        "sender": sender,
        "subject": subject,
        "rspamd_score": rspamd_score,
        "processed_time_ms": processed_ms,
        "created_at": created_at,
    }

    # Best-effort persistence — never block the response on these.
    if not from_cache and chash:
        rds = _safe_load_redis()
        if rds is not None:
            try:
                rds.set(
                    f"ai:result:{chash}",
                    json.dumps(result, ensure_ascii=False),
                    ex=_CACHE_TTL_SEC,
                )
            except Exception:
                pass
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
        "is_phishing": False,
        "confidence": 0.0,
        "reason": "step3 unhandled exception; defaulting add_score=0",
        "suggested_action": "放行",
        "from_cache": False,
    }, ensure_ascii=False) + "\n")
    sys.exit(0)
'''


__all__ = ["PHISHING_STEP1_CODE", "PHISHING_STEP3_CODE"]

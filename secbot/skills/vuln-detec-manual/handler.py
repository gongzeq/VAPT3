"""vuln-detec-manual handler.

Automated lightweight vulnerability verification against Web endpoints.
Performs 8 systematic read-only probes per target URL and returns
structured findings with confidence ratings.
"""

from __future__ import annotations

import ipaddress
import random
import re
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from secbot.skills.types import SkillContext, SkillResult

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SQL_ERROR_KEYWORDS = re.compile(
    r"sql|syntax|mysql|postgres|oracle|sqlite|error|warning|exception",
    re.IGNORECASE,
)
_ID_OUTPUT_RE = re.compile(r"uid=\d+\(\w+\)\s+gid=\d+\(\w+\)")
_DEFAULT_UA = "Mozilla/5.0 (secbot-vuln-detec)"
_MAX_BODY_SNIPPET = 256

_TEST_TO_CATEGORY: dict[str, str] = {
    "XSS Reflection": "xss",
    "SQL Error Probe": "injection",
    "Time-based SQLi": "injection",
    "Numeric Arithmetic": "injection",
    "Template Injection": "injection",
    "Command Injection": "injection",
    "Special Character Handling": "other",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _host_from_url(url: str) -> str:
    """Extract hostname from URL (netloc without port)."""
    parsed = urlparse(url)
    host = parsed.hostname or parsed.netloc or url
    return host


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _build_headers(
    global_headers: dict[str, str] | None,
    target_headers: dict[str, str] | None,
    cookie_str: str | None,
) -> dict[str, str]:
    """Merge global + per-target headers; per-target wins."""
    headers: dict[str, str] = {}
    if global_headers:
        headers.update(global_headers)
    if target_headers:
        headers.update(target_headers)
    headers.setdefault("User-Agent", _DEFAULT_UA)
    if cookie_str:
        headers["Cookie"] = cookie_str
    return headers


def _snippet(text: str, max_len: int = _MAX_BODY_SNIPPET) -> str:
    """Return a bounded, one-line snippet of *text*."""
    t = text.replace("\n", " ").replace("\r", " ").strip()
    if len(t) > max_len:
        t = t[: max_len - 3] + "..."
    return t


def _inject_param(params: dict[str, Any], payload: str) -> dict[str, Any]:
    """Replace the first parameter value with *payload*."""
    if not params:
        return params
    injected = dict(params)
    first_key = next(iter(injected))
    injected[first_key] = payload
    return injected


# ---------------------------------------------------------------------------
# HTTP request wrapper
# ---------------------------------------------------------------------------


async def _request(
    client: httpx.AsyncClient,
    url: str,
    method: str,
    params: dict[str, Any] | None,
    headers: dict[str, str],
) -> httpx.Response:
    """Send one HTTP request and return the response."""
    if method.upper() == "POST":
        # POST with form data when params exist; otherwise plain POST
        if params:
            return await client.post(url, data=params, headers=headers)
        return await client.post(url, headers=headers)
    return await client.get(url, params=params, headers=headers)


# ---------------------------------------------------------------------------
# 8 probes
# ---------------------------------------------------------------------------


async def _probe_baseline(
    client: httpx.AsyncClient,
    url: str,
    method: str,
    params: dict[str, Any] | None,
    headers: dict[str, str],
) -> dict[str, Any] | None:
    """Return baseline metrics: status, length, elapsed_ms."""
    try:
        start = time.monotonic()
        resp = await _request(client, url, method, params, headers)
        elapsed_ms = (time.monotonic() - start) * 1000
        return {
            "status": resp.status_code,
            "length": len(resp.text),
            "elapsed_ms": elapsed_ms,
        }
    except Exception:
        return None


async def _probe_special_char(
    client: httpx.AsyncClient,
    url: str,
    method: str,
    params: dict[str, Any] | None,
    headers: dict[str, str],
    baseline: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not params or baseline is None:
        return None
    payload = "test'\"<>(){}"
    try:
        resp = await _request(
            client, url, method, _inject_param(params, payload), headers
        )
        diff = abs(len(resp.text) - baseline["length"])
        if diff > 50:
            return {
                "test_name": "Special Character Handling",
                "result": "positive",
                "confidence": "medium",
                "evidence": f"Response size changed by {diff} bytes",
                "payload": payload,
                "url": url,
            }
    except Exception:
        pass
    return None


async def _probe_xss(
    client: httpx.AsyncClient,
    url: str,
    method: str,
    params: dict[str, Any] | None,
    headers: dict[str, str],
) -> dict[str, Any] | None:
    if not params:
        return None
    marker = f"secbot{random.randint(1000, 9999)}"
    try:
        resp = await _request(
            client, url, method, _inject_param(params, marker), headers
        )
        if marker in resp.text:
            # Check if <script> is reflected unescaped
            script_test = await _request(
                client, url, method, _inject_param(params, "<script>"), headers
            )
            raw_script = "<script>" in script_test.text
            escaped = "&lt;script&gt;" in script_test.text

            if raw_script and not escaped:
                confidence = "high"
                evidence = "Marker and <script> reflected unescaped"
            else:
                confidence = "medium"
                evidence = "Marker reflected but script appears encoded"

            return {
                "test_name": "XSS Reflection",
                "result": "positive",
                "confidence": confidence,
                "evidence": evidence,
                "payload": marker,
                "url": url,
            }
    except Exception:
        pass
    return None


async def _probe_sql_error(
    client: httpx.AsyncClient,
    url: str,
    method: str,
    params: dict[str, Any] | None,
    headers: dict[str, str],
) -> dict[str, Any] | None:
    if not params:
        return None
    payload = "'"
    try:
        resp = await _request(
            client, url, method, _inject_param(params, payload), headers
        )
        matches = _SQL_ERROR_KEYWORDS.findall(resp.text)
        if matches:
            unique = sorted(set(m.lower() for m in matches))
            return {
                "test_name": "SQL Error Probe",
                "result": "positive",
                "confidence": "high",
                "evidence": f"SQL error keywords: {', '.join(unique)} — {_snippet(resp.text)}",
                "payload": payload,
                "url": url,
            }
    except Exception:
        pass
    return None


async def _probe_time_sqli(
    client: httpx.AsyncClient,
    url: str,
    method: str,
    params: dict[str, Any] | None,
    headers: dict[str, str],
    baseline: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not params or baseline is None:
        return None
    # Append time-delay payload to the first param value
    first_key = next(iter(params))
    original = str(params[first_key])
    payload = f"{original}' AND SLEEP(3)--"
    injected = dict(params)
    injected[first_key] = payload

    try:
        start = time.monotonic()
        await _request(client, url, method, injected, headers)
        elapsed = time.monotonic() - start
        baseline_sec = baseline["elapsed_ms"] / 1000

        if elapsed >= baseline_sec + 2.5:
            return {
                "test_name": "Time-based SQLi",
                "result": "positive",
                "confidence": "high",
                "evidence": (
                    f"Response delayed {elapsed:.1f}s "
                    f"(baseline ~{baseline_sec:.1f}s)"
                ),
                "payload": payload,
                "url": url,
            }
    except Exception:
        pass
    return None


async def _probe_numeric(
    client: httpx.AsyncClient,
    url: str,
    method: str,
    params: dict[str, Any] | None,
    headers: dict[str, str],
) -> dict[str, Any] | None:
    if not params:
        return None

    # Find the first numeric parameter
    numeric_key: str | None = None
    numeric_val: int | None = None
    for k, v in params.items():
        try:
            numeric_val = int(v)
            numeric_key = k
            break
        except (ValueError, TypeError):
            continue

    if numeric_key is None or numeric_val is None:
        return None

    try:
        resp1 = await _request(client, url, method, params, headers)

        injected = dict(params)
        injected[numeric_key] = f"{numeric_val + 1}-1"
        resp2 = await _request(client, url, method, injected, headers)

        if resp1.text == resp2.text:
            return {
                "test_name": "Numeric Arithmetic",
                "result": "positive",
                "confidence": "medium",
                "evidence": (
                    f"'{numeric_val + 1}-1' produced same response as '{numeric_val}'"
                ),
                "payload": f"{numeric_val + 1}-1",
                "url": url,
            }
    except Exception:
        pass
    return None


async def _probe_template(
    client: httpx.AsyncClient,
    url: str,
    method: str,
    params: dict[str, Any] | None,
    headers: dict[str, str],
) -> dict[str, Any] | None:
    if not params:
        return None
    payloads = ["{{7*7}}", "${7*7}"]
    for payload in payloads:
        try:
            resp = await _request(
                client, url, method, _inject_param(params, payload), headers
            )
            if "49" in resp.text:
                return {
                    "test_name": "Template Injection",
                    "result": "positive",
                    "confidence": "high",
                    "evidence": "Expression evaluated: 7*7=49 found in response",
                    "payload": payload,
                    "url": url,
                }
        except Exception:
            pass
    return None


async def _probe_command(
    client: httpx.AsyncClient,
    url: str,
    method: str,
    params: dict[str, Any] | None,
    headers: dict[str, str],
) -> dict[str, Any] | None:
    if not params:
        return None
    # Use harmless payloads only (id command output is benign)
    payloads = [";id", "|id", "$(id)", "`id`"]
    for payload in payloads:
        try:
            resp = await _request(
                client, url, method, _inject_param(params, payload), headers
            )
            if _ID_OUTPUT_RE.search(resp.text):
                return {
                    "test_name": "Command Injection",
                    "result": "positive",
                    "confidence": "high",
                    "evidence": "id command output detected in response",
                    "payload": payload,
                    "url": url,
                }
        except Exception:
            pass
    return None


# ---------------------------------------------------------------------------
# Target sweep
# ---------------------------------------------------------------------------


async def _sweep_target(
    client: httpx.AsyncClient,
    target: dict[str, Any],
    global_headers: dict[str, str] | None,
) -> list[dict[str, Any]]:
    """Run all 8 probes against one target and return findings."""
    url: str = target["url"]
    method: str = target.get("method", "GET")
    params: dict[str, Any] | None = target.get("params")
    headers = _build_headers(
        global_headers, target.get("headers"), target.get("cookies")
    )

    findings: list[dict[str, Any]] = []

    baseline = await _probe_baseline(client, url, method, params, headers)

    probes = [
        _probe_special_char(client, url, method, params, headers, baseline),
        _probe_xss(client, url, method, params, headers),
        _probe_sql_error(client, url, method, params, headers),
        _probe_time_sqli(client, url, method, params, headers, baseline),
        _probe_numeric(client, url, method, params, headers),
        _probe_template(client, url, method, params, headers),
        _probe_command(client, url, method, params, headers),
    ]

    for coro in probes:
        finding = await coro
        if finding is not None:
            findings.append(finding)

    return findings


# ---------------------------------------------------------------------------
# CMDB writes
# ---------------------------------------------------------------------------


def _findings_to_cmdb_writes(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate high-confidence findings into vulnerabilities table writes."""
    writes: list[dict[str, Any]] = []
    for f in findings:
        if f.get("confidence") != "high":
            continue
        test_name = f.get("test_name", "unknown")
        category = _TEST_TO_CATEGORY.get(test_name, "other")
        host = _host_from_url(f.get("url", ""))
        writes.append(
            {
                "table": "vulnerabilities",
                "op": "upsert",
                "data": {
                    "target": host,
                    "severity": "high",
                    "category": category,
                    "title": f"{test_name} detected",
                    "evidence": f.get("evidence", ""),
                },
            }
        )
    return writes


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


async def run(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    targets: list[dict[str, Any]] = args["targets"]
    timeout_sec: int = int(args.get("timeout_sec", 30))
    global_headers: dict[str, str] | None = args.get("global_headers")

    all_findings: list[dict[str, Any]] = []

    async with httpx.AsyncClient(
        timeout=timeout_sec,
        follow_redirects=False,
    ) as client:
        for target in targets:
            findings = await _sweep_target(client, target, global_headers)
            all_findings.extend(findings)

    high_confidence = sum(1 for f in all_findings if f.get("confidence") == "high")

    summary = {
        "targets": len(targets),
        "findings": len(all_findings),
        "high_confidence": high_confidence,
    }

    cmdb_writes = _findings_to_cmdb_writes(all_findings)

    return SkillResult(
        summary=summary,
        raw_log_path=str(ctx.raw_log_dir / "vuln-detec-manual.log"),
        findings=all_findings,
        cmdb_writes=cmdb_writes,
    )

"""ffuf-specific shared helpers.

Centralises every argv fragment, validator and JSON-result parser that is
shared by :mod:`secbot.skills.ffuf-dir-fuzz` and
:mod:`secbot.skills.ffuf-vhost-fuzz`. The goal is to sink the *complete*
ffuf usage surface described in the upstream skill
(`ffuf_claude_skill-main/ffuf-skill/SKILL.md`) — matchers/filters,
auto-calibration, rate control, recursion, raw-request mode, cookies,
proxies, JSON result parsing — while keeping both handlers a thin
url-/host-template-specific wrapper on top.

All validators raise :class:`InvalidSkillArg` before the sandbox sees the
argv, so operators get a friendly error instead of
``InvalidArgvCharacter`` buried in the subprocess layer. The forbidden
character set mirrors
``secbot.skills._shared.sandbox.FORBIDDEN_CHARS`` exactly.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Sequence

from secbot.skills.types import InvalidSkillArg

# Keep this in lock-step with
# secbot.skills._shared.sandbox.FORBIDDEN_CHARS.
_FORBIDDEN_CHARS = frozenset(";&|$`<>\n\r\\\"'")

# Compact numeric / range spec, e.g. ``200,204,301-302,400-499``. ffuf reuses
# the same grammar for -mc/-ms/-mw/-ml and the matching -fc/-fs/-fw/-fl.
_RANGE_SPEC_RE = re.compile(r"^[0-9,\-]{1,128}$")

# ffuf delay is either ``<float>`` or ``<float>-<float>`` seconds.
_DELAY_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)?(?:-[0-9]+(?:\.[0-9]+)?)?$")

# HTTP header name grammar (RFC 7230 token, trimmed to what ffuf accepts).
_HEADER_NAME_RE = re.compile(r"^[A-Za-z0-9!#$%&'*+\-.^_`|~]{1,64}$")

# Cookie segment: ``name=value``. Forbidden chars are checked separately.
_COOKIE_RE = re.compile(r"^[A-Za-z0-9_\-.]{1,64}=[^\s;]{0,512}$")

# HTTP methods we allow.
_METHOD_RE = re.compile(r"^[A-Z]{3,10}$")

# Absolute per-run limits that would be suicidal to exceed even with an
# explicit operator override.
_MAX_THREADS = 200
_MAX_RATE = 500_000
_MAX_TIMEOUT_SEC = 7_200
_MAX_JOB_TIMEOUT_SEC = 3_600
_MAX_RECURSION_DEPTH = 5
_MAX_WORDLIST = 50_000


# ---------------------------------------------------------------------------
# Primitive validators
# ---------------------------------------------------------------------------


def ensure_no_forbidden(label: str, value: str) -> None:
    """Reject any user-supplied argv element containing shell metacharacters."""
    bad = _FORBIDDEN_CHARS.intersection(value)
    if bad:
        raise InvalidSkillArg(
            f"{label} contains forbidden character(s) {sorted(bad)}: {value!r}"
        )


def ensure_fuzz_marker(label: str, value: str) -> None:
    if "FUZZ" not in value:
        raise InvalidSkillArg(f"{label} must contain the 'FUZZ' marker")


def validate_range_spec(label: str, value: str) -> None:
    if not _RANGE_SPEC_RE.match(value):
        raise InvalidSkillArg(
            f"{label} must match /^[0-9,\\-]+$/ (e.g. '200,301-302'): {value!r}"
        )


def validate_method(value: str) -> None:
    if not _METHOD_RE.match(value):
        raise InvalidSkillArg(f"invalid HTTP method: {value!r}")


def validate_header(value: str) -> None:
    ensure_no_forbidden("header", value)
    if ":" not in value:
        raise InvalidSkillArg(f"header must be 'Name: Value': {value!r}")
    name = value.split(":", 1)[0].strip()
    if not _HEADER_NAME_RE.match(name):
        raise InvalidSkillArg(f"invalid header name: {name!r}")


def validate_cookie(value: str) -> None:
    ensure_no_forbidden("cookie", value)
    if not _COOKIE_RE.match(value):
        raise InvalidSkillArg(
            f"cookie must be 'name=value' with URL-safe chars: {value!r}"
        )


def validate_wordlist(entries: Sequence[str], *, allow_space: bool = True) -> None:
    if not entries:
        raise InvalidSkillArg("wordlist must be a non-empty list")
    if len(entries) > _MAX_WORDLIST:
        raise InvalidSkillArg(
            f"wordlist too large: {len(entries)} > {_MAX_WORDLIST}"
        )
    for w in entries:
        if not isinstance(w, str):
            raise InvalidSkillArg(f"wordlist entry must be str: {w!r}")
        if not w:
            raise InvalidSkillArg("wordlist entry must not be empty")
        if "\n" in w or "\r" in w or "\t" in w:
            raise InvalidSkillArg(
                f"wordlist entry may not contain tab / newline: {w!r}"
            )
        if not allow_space and " " in w:
            raise InvalidSkillArg(
                f"wordlist entry may not contain space (vhost mode): {w!r}"
            )


# ---------------------------------------------------------------------------
# On-disk materialisation (wordlists + raw request template)
# ---------------------------------------------------------------------------


def materialise_wordlist(entries: Sequence[str], dest: Path) -> Path:
    """Write *entries* to *dest* (one per line) and return the path."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(entries) + "\n", encoding="utf-8")
    return dest


def materialise_raw_request(text: str, dest: Path) -> Path:
    """Persist a raw HTTP request template so ffuf can consume it via ``--request``.

    Upstream usage (see SKILL.md §"Using Raw HTTP Requests") is:

        ffuf --request req.txt -w wordlist.txt -ac

    where ``req.txt`` is an authenticated request captured from Burp /
    DevTools with the FUZZ marker placed where the fuzzing should happen.
    We do not parse the HTTP grammar here — ffuf does — but we do require a
    FUZZ marker and a reasonable size bound.
    """
    if "FUZZ" not in text:
        raise InvalidSkillArg("raw_request must contain the 'FUZZ' marker")
    if len(text) > 64 * 1024:
        raise InvalidSkillArg("raw_request exceeds 64KiB")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    return dest


# ---------------------------------------------------------------------------
# argv builder for the options both skills share
# ---------------------------------------------------------------------------


def build_common_argv(
    opts: dict[str, Any],
    *,
    results_file: Path,
) -> list[str]:
    """Translate the options shared by both ffuf skills into argv fragments.

    Returns the flags; the caller still appends the skill-specific bits
    (``-u``, ``-H "Host: FUZZ.example.com"``, ``-w wordlist:FUZZ`` and so
    on). This keeps the shared code free of knowledge about whether the
    marker lives in the URL or in a header.
    """
    cli: list[str] = []

    # ---------- Matchers ----------
    if "match_codes" in opts and opts["match_codes"]:
        validate_range_spec("match_codes", opts["match_codes"])
        cli += ["-mc", opts["match_codes"]]
    if opts.get("match_sizes"):
        validate_range_spec("match_sizes", opts["match_sizes"])
        cli += ["-ms", opts["match_sizes"]]
    if opts.get("match_words"):
        validate_range_spec("match_words", opts["match_words"])
        cli += ["-mw", opts["match_words"]]
    if opts.get("match_lines"):
        validate_range_spec("match_lines", opts["match_lines"])
        cli += ["-ml", opts["match_lines"]]
    if opts.get("match_regex"):
        ensure_no_forbidden("match_regex", opts["match_regex"])
        cli += ["-mr", opts["match_regex"]]

    # ---------- Filters ----------
    if opts.get("filter_codes"):
        validate_range_spec("filter_codes", opts["filter_codes"])
        cli += ["-fc", opts["filter_codes"]]
    if opts.get("filter_sizes"):
        validate_range_spec("filter_sizes", opts["filter_sizes"])
        cli += ["-fs", opts["filter_sizes"]]
    if opts.get("filter_words"):
        validate_range_spec("filter_words", opts["filter_words"])
        cli += ["-fw", opts["filter_words"]]
    if opts.get("filter_lines"):
        validate_range_spec("filter_lines", opts["filter_lines"])
        cli += ["-fl", opts["filter_lines"]]
    if opts.get("filter_regex"):
        ensure_no_forbidden("filter_regex", opts["filter_regex"])
        cli += ["-fr", opts["filter_regex"]]

    # ---------- Auto-calibration ----------
    # Upstream guidance: **ALWAYS** use -ac unless there is a specific reason
    # not to. We therefore default to True when the caller hasn't expressed
    # an opinion. The per-host variant (``-ach``) supersedes the plain one.
    if opts.get("auto_calibrate_per_host"):
        cli += ["-ach"]
    elif opts.get("auto_calibrate", True):
        cli += ["-ac"]
    for s in opts.get("auto_calibrate_strings", []) or []:
        ensure_no_forbidden("auto_calibrate_strings", s)
        cli += ["-acc", s]

    # ---------- Threads / rate / timing ----------
    threads = int(opts.get("threads", 40))
    if threads < 1 or threads > _MAX_THREADS:
        raise InvalidSkillArg(f"threads out of range (1..{_MAX_THREADS}): {threads!r}")
    cli += ["-t", str(threads)]

    if opts.get("rate") is not None:
        rate = int(opts["rate"])
        if rate < 0 or rate > _MAX_RATE:
            raise InvalidSkillArg(f"rate out of range: {rate!r}")
        cli += ["-rate", str(rate)]

    if opts.get("delay"):
        if not _DELAY_RE.match(opts["delay"]):
            raise InvalidSkillArg(
                f"delay must be 'X' or 'X-Y' seconds: {opts['delay']!r}"
            )
        cli += ["-p", opts["delay"]]

    if opts.get("max_time_sec"):
        v = int(opts["max_time_sec"])
        if v <= 0 or v > _MAX_TIMEOUT_SEC:
            raise InvalidSkillArg(f"max_time_sec out of range: {v!r}")
        cli += ["-maxtime", str(v)]

    if opts.get("max_time_job_sec"):
        v = int(opts["max_time_job_sec"])
        if v <= 0 or v > _MAX_JOB_TIMEOUT_SEC:
            raise InvalidSkillArg(f"max_time_job_sec out of range: {v!r}")
        cli += ["-maxtime-job", str(v)]

    # ---------- Recursion ----------
    if opts.get("recursion"):
        cli += ["-recursion"]
        depth = int(opts.get("recursion_depth", 2))
        if depth < 1 or depth > _MAX_RECURSION_DEPTH:
            raise InvalidSkillArg(
                f"recursion_depth out of range (1..{_MAX_RECURSION_DEPTH}): {depth!r}"
            )
        cli += ["-recursion-depth", str(depth)]

    # ---------- Headers / cookies ----------
    for h in opts.get("headers", []) or []:
        validate_header(h)
        cli += ["-H", h]
    for c in opts.get("cookies", []) or []:
        validate_cookie(c)
        cli += ["-b", c]

    # ---------- Proxies ----------
    if opts.get("proxy"):
        ensure_no_forbidden("proxy", opts["proxy"])
        cli += ["-x", opts["proxy"]]
    if opts.get("replay_proxy"):
        ensure_no_forbidden("replay_proxy", opts["replay_proxy"])
        cli += ["-replay-proxy", opts["replay_proxy"]]

    # ---------- Misc ----------
    if opts.get("ignore_body"):
        cli += ["-ignore-body"]
    if opts.get("follow_redirects"):
        cli += ["-r"]
    if opts.get("stop_on_error"):
        cli += ["-se"]

    # ---------- Output (always JSON + silent for deterministic parsing) ----
    cli += ["-of", "json", "-o", str(results_file), "-s"]

    return cli


# ---------------------------------------------------------------------------
# Result parser
# ---------------------------------------------------------------------------


def _duration_ms(raw: Any) -> int:
    """ffuf stores per-request duration as Go ``time.Duration`` (ns int)."""
    if isinstance(raw, int):
        return raw // 1_000_000
    if isinstance(raw, float):
        return int(raw // 1_000_000)
    return 0


def parse_results_json(
    results_file: Path, *, marker: str = "FUZZ", limit: int = 500
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read ``ffuf -of json`` output and normalise it for summary payloads.

    Returns ``(entries, meta)`` where *entries* is the list of
    hit dictionaries (up to *limit*) and *meta* contains the ffuf-level
    metadata + any parser errors we want to surface.
    """
    meta: dict[str, Any] = {}
    if not results_file.exists():
        return [], {"parse_error": "results file not produced"}
    try:
        data = json.loads(results_file.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        return [], {"parse_error": str(exc)[:200]}

    raw_results = data.get("results") or []
    meta["total_hits"] = len(raw_results)
    if data.get("commandline"):
        meta["command_line"] = data.get("commandline")[:512]

    normalised: list[dict[str, Any]] = []
    for r in raw_results[:limit]:
        inputs = r.get("input") or {}
        normalised.append(
            {
                "url": r.get("url", ""),
                "input": inputs.get(marker) if isinstance(inputs, dict) else "",
                "status": int(r.get("status", 0) or 0),
                "length": int(r.get("length", 0) or 0),
                "words": int(r.get("words", 0) or 0),
                "lines": int(r.get("lines", 0) or 0),
                "duration_ms": _duration_ms(r.get("duration")),
                "content_type": r.get("content-type", "") or "",
                "redirect_location": r.get("redirectlocation", "") or "",
                "host": r.get("host", "") or "",
            }
        )
    return normalised, meta

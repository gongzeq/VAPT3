"""katana-crawl-web handler.

Runs ProjectDiscovery Katana against one authorized HTTP/HTTPS target, then
reduces the crawled URL set into bounded vulnerability hypotheses for the
orchestrator to route onward.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import SplitResult, parse_qsl, unquote_plus, urlsplit, urlunsplit

from secbot.skills._shared import NetworkPolicy, run_command
from secbot.skills.types import (
    InvalidSkillArg,
    SkillBinaryMissing,
    SkillCancelled,
    SkillContext,
    SkillResult,
    SkillTimeout,
)

_TARGET_RE = re.compile(
    r"^https?://[A-Za-z0-9][A-Za-z0-9._~:/?#\[\]@!()*+,=%-]{0,2047}$"
)
_HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-]*[A-Za-z0-9]$")
_FORBIDDEN_TARGET_CHARS = frozenset(";&|$`<>\n\r\\\"'")

_STATIC_EXTENSIONS = {
    ".css",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".map",
    ".png",
    ".svg",
    ".ttf",
    ".webp",
    ".woff",
    ".woff2",
}
_KATANA_EXCLUDED_EXTENSIONS = ("css", "png", "jpg", "gif", "svg", "woff", "ttf", "js")

_CRITICAL_PARAMS = {
    "cmd",
    "exec",
    "command",
    "file",
    "path",
    "url",
    "uri",
    "template",
    "query",
}
_HIGH_PARAMS = {"id", "userid", "user_id", "username", "xml", "data", "payload"}
_SKIP_PARAMS = {"color", "theme", "page_size", "lang", "sort", "order"}

_BUSINESS_PATH_KEYWORDS = {
    "admin",
    "download",
    "export",
    "fetch",
    "import",
    "login",
    "upload",
}
_STATIC_API_KEYWORDS = {
    "city",
    "country",
    "dict",
    "dictionary",
    "locale",
    "province",
    "region",
    "static",
}

_MAX_URLS = 10_000
_MAX_CANDIDATES = 500


def _resolve_katana_binary(cli: list[str]) -> tuple[str, list[str]]:
    """Return (binary, args) for Katana, honouring config overrides."""
    import shutil

    from secbot.config.loader import load_config

    cfg = load_config()
    override = cfg.tools.skill_binaries.get("katana")
    if override:
        if not Path(override).exists():
            raise SkillBinaryMissing(
                f"Configured katana override not found: {override}. "
                "Check tools.skillBinaries.katana in your config."
            )
        return override, cli
    if shutil.which("katana"):
        return "katana", cli
    raise SkillBinaryMissing(
        "katana not found on PATH. "
        "Install ProjectDiscovery Katana or set tools.skillBinaries.katana in ~/.secbot/config.json"
    )


def _validate_target(target: str) -> str:
    if not isinstance(target, str) or not _TARGET_RE.match(target):
        raise InvalidSkillArg(f"invalid target: {target!r}")
    if _FORBIDDEN_TARGET_CHARS.intersection(target):
        raise InvalidSkillArg("target contains forbidden character")

    try:
        parts = urlsplit(target)
    except ValueError as exc:
        raise InvalidSkillArg(f"invalid target URL: {target!r}") from exc
    if parts.scheme not in {"http", "https"} or not parts.netloc or not parts.hostname:
        raise InvalidSkillArg(f"target must be an HTTP/HTTPS URL: {target!r}")
    if parts.username or parts.password:
        raise InvalidSkillArg("target URL must not contain credentials")
    if not _HOST_RE.match(parts.hostname):
        raise InvalidSkillArg(f"invalid target host: {parts.hostname!r}")
    try:
        port = parts.port
    except ValueError as exc:
        raise InvalidSkillArg(f"invalid target port: {target!r}") from exc
    if port is not None and not (1 <= port <= 65535):
        raise InvalidSkillArg(f"invalid target port: {port!r}")
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path or "", parts.query, "")
    )


def _bounded_int(
    value: Any, *, default: int, minimum: int, maximum: int, name: str
) -> int:
    if value is None:
        return default
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise InvalidSkillArg(f"{name} must be an integer") from exc
    if out < minimum or out > maximum:
        raise InvalidSkillArg(f"{name} out of range: {out!r}")
    return out


def _normalise_url(raw: str) -> str | None:
    value = raw.strip()
    if not value:
        return None
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    try:
        parts.port
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    netloc = parts.netloc.lower()
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), netloc, path, parts.query, ""))


def _effective_port(parts: SplitResult) -> int | None:
    try:
        port = parts.port
    except ValueError:
        return -1
    if port is None:
        return None
    if parts.scheme == "http" and port == 80:
        return None
    if parts.scheme == "https" and port == 443:
        return None
    return port


def _is_in_target_scope(url: str, target: str) -> bool:
    """Keep Katana output scoped to the authorized target host/port."""
    try:
        candidate = urlsplit(url)
        root = urlsplit(target)
        candidate_host = candidate.hostname
        root_host = root.hostname
    except ValueError:
        return False
    if candidate.scheme not in {"http", "https"}:
        return False
    if not candidate_host or not root_host:
        return False
    return (
        candidate_host.lower() == root_host.lower()
        and _effective_port(candidate) == _effective_port(root)
    )


def _read_deduped_urls(urls_file: Path) -> tuple[int, list[str]]:
    total = 0
    seen: set[str] = set()
    urls: list[str] = []
    if not urls_file.exists():
        return 0, []

    with urls_file.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            total += 1
            if total > _MAX_URLS:
                break
            normalised = _normalise_url(line)
            if normalised is None or normalised in seen:
                continue
            seen.add(normalised)
            urls.append(normalised)
    return total, urls


def _path_segments(path: str) -> list[str]:
    segments: list[str] = []
    for segment in path.split("/"):
        decoded = unquote_plus(segment).lower()
        if not decoded:
            continue
        segments.append(decoded)
        segments.extend(token for token in re.split(r"[^a-z0-9]+", decoded) if token)
    return _unique(segments)


def _is_static_asset(path: str) -> bool:
    lower = unquote_plus(path).lower()
    return any(lower.endswith(ext) for ext in _STATIC_EXTENSIONS)


def _is_static_dictionary_api(path: str, params: list[tuple[str, str]]) -> bool:
    segments = set(_path_segments(path))
    if not segments.intersection(_STATIC_API_KEYWORDS):
        return False
    if not params:
        return True
    names = {_normalise_param_name(name) for name, _value in params}
    return names.issubset(_SKIP_PARAMS | {"code", "type", "parent", "parent_id", "pid"})


def _normalise_param_name(name: str) -> str:
    lowered = unquote_plus(name).strip().lower()
    return lowered.replace(" ", "_").replace("-", "_")


def _classify_param(name: str) -> str:
    normalised = _normalise_param_name(name)
    compact = normalised.replace("_", "")
    if normalised in _CRITICAL_PARAMS or compact in _CRITICAL_PARAMS:
        return "critical"
    if normalised in _HIGH_PARAMS or compact in _HIGH_PARAMS:
        return "high"
    if normalised in _SKIP_PARAMS or compact in _SKIP_PARAMS:
        return "skipped"
    return "neutral"


def _content_hints(params: list[tuple[str, str]]) -> tuple[list[str], list[str]]:
    vulnerabilities: list[str] = []
    reasons: list[str] = []

    for name, value in params:
        decoded_name = _normalise_param_name(name)
        decoded_value = unquote_plus(value).strip()
        lower_value = decoded_value.lower()

        if (
            "\"@type\"" in decoded_value
            or "'@type'" in decoded_value
            or re.search(
                r"\b[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){2,}\b",
                decoded_value,
            )
        ):
            vulnerabilities.append("json_deserialization")
            reasons.append(
                "query value contains JSON deserialization class/type indicators"
            )

        if (
            decoded_name == "xml"
            or lower_value.startswith("<?xml")
            or "<!doctype" in lower_value
            or re.search(r"<[a-zA-Z][^>]{0,80}>", decoded_value)
        ):
            vulnerabilities.append("xxe")
            reasons.append("XML-looking parameter or value suitable for XXE testing")

    return _unique(vulnerabilities), _unique(reasons)


def _path_hints(path: str) -> tuple[list[str], list[str]]:
    segments = set(_path_segments(path))
    vulnerabilities: list[str] = []
    reasons: list[str] = []

    if segments.intersection({"upload", "import"}):
        vulnerabilities.extend(["file_upload", "access_control"])
        reasons.append("business-sensitive upload/import path")
    if segments.intersection({"download", "export"}):
        vulnerabilities.extend(["path_traversal", "idor", "access_control"])
        reasons.append("business-sensitive download/export path")
    if "fetch" in segments:
        vulnerabilities.extend(["ssrf", "open_redirect"])
        reasons.append("fetch path may dereference attacker-controlled URLs")
    if segments.intersection({"admin", "login"}):
        vulnerabilities.extend(["auth_bypass", "weak_auth"])
        reasons.append("admin/login path deserves authentication and access-control checks")

    return _unique(vulnerabilities), _unique(reasons)


def _parameter_hypotheses(parameters: list[dict[str, str]]) -> tuple[list[str], list[str]]:
    vulnerabilities: list[str] = []
    reasons: list[str] = []
    for param in parameters:
        name = param["name"]
        risk = param["risk"]
        normalised = _normalise_param_name(name)
        if risk == "critical":
            if normalised in {"cmd", "exec", "command"}:
                vulnerabilities.append("command_injection")
            elif normalised in {"file", "path", "template"}:
                vulnerabilities.extend(["path_traversal", "file_inclusion", "ssti"])
            elif normalised in {"url", "uri"}:
                vulnerabilities.extend(["ssrf", "open_redirect"])
            elif normalised == "query":
                vulnerabilities.append("injection")
            reasons.append(f"critical parameter name: {name}")
        elif risk == "high":
            if normalised in {"id", "userid", "user_id", "username"}:
                vulnerabilities.append("idor")
            elif normalised == "xml":
                vulnerabilities.append("xxe")
            elif normalised in {"data", "payload"}:
                vulnerabilities.extend(["deserialization", "injection"])
            reasons.append(f"high-risk parameter name: {name}")
    return _unique(vulnerabilities), _unique(reasons)


def _priority(parameters: list[dict[str, str]], vulnerabilities: list[str], path: str) -> str:
    risks = {p["risk"] for p in parameters}
    if (
        "critical" in risks
        or "command_injection" in vulnerabilities
        or "json_deserialization" in vulnerabilities
        or "xxe" in vulnerabilities
    ):
        return "critical"
    if "high" in risks:
        return "high"
    if set(_path_segments(path)).intersection(_BUSINESS_PATH_KEYWORDS) or vulnerabilities:
        return "medium"
    return "low"


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _build_candidate(url: str) -> dict[str, Any] | None:
    parts = urlsplit(url)
    params = parse_qsl(parts.query, keep_blank_values=True)

    if _is_static_asset(parts.path):
        return None
    if _is_static_dictionary_api(parts.path, params):
        return None

    parameters = [
        {"name": name, "risk": _classify_param(name)}
        for name, _value in params
    ]
    kept_parameters = [p for p in parameters if p["risk"] != "skipped"]

    vulnerabilities: list[str] = []
    reasons: list[str] = []

    param_vulns, param_reasons = _parameter_hypotheses(parameters)
    vulnerabilities.extend(param_vulns)
    reasons.extend(param_reasons)

    content_vulns, content_reasons = _content_hints(params)
    vulnerabilities.extend(content_vulns)
    reasons.extend(content_reasons)

    path_vulns, path_reasons = _path_hints(parts.path)
    vulnerabilities.extend(path_vulns)
    reasons.extend(path_reasons)

    only_low_value_params = bool(parameters) and not kept_parameters
    if only_low_value_params and not path_reasons and not content_reasons:
        return None
    if not kept_parameters and not vulnerabilities and not path_reasons:
        return None

    vulnerabilities = _unique(vulnerabilities) or ["manual_review"]
    reasons = _unique(reasons) or ["parameterized endpoint discovered by crawler"]
    priority = _priority(parameters, vulnerabilities, parts.path)

    return {
        "url": url,
        "priority": priority,
        "parameters": parameters,
        "guessed_vulnerabilities": vulnerabilities,
        "reasons": reasons[:6],
        "recommended_action": _recommended_action(priority, vulnerabilities),
    }


def _recommended_action(priority: str, vulnerabilities: list[str]) -> str:
    vuln_list = ", ".join(vulnerabilities[:4])
    if priority in {"critical", "high"}:
        return f"route_to_vuln_scan: verify {vuln_list}"
    if priority == "medium":
        return f"route_to_vuln_scan_if_in_scope: verify {vuln_list}"
    return "manual_review_if_time_allows"


def _parse_urls(urls_file: Path, max_candidates: int, target: str) -> dict[str, Any]:
    total_urls, deduped = _read_deduped_urls(urls_file)
    candidates: list[dict[str, Any]] = []
    filtered_urls = 0

    for url in deduped:
        if not _is_in_target_scope(url, target):
            filtered_urls += 1
            continue
        candidate = _build_candidate(url)
        if candidate is None:
            filtered_urls += 1
            continue
        candidates.append(candidate)

    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    candidates.sort(key=lambda item: priority_order[item["priority"]])
    shown = candidates[:max_candidates]
    summary: dict[str, Any] = {
        "total_urls": total_urls,
        "deduped_urls": len(deduped),
        "filtered_urls": filtered_urls,
        "candidate_count": len(candidates),
        "candidates": shown,
        "raw_urls_path": str(urls_file),
    }
    if len(shown) < len(candidates):
        summary["_truncated"] = {
            "candidates": {
                "shown": len(shown),
                "total": len(candidates),
                "raw_log_path": str(urls_file),
            }
        }

    return summary


async def run(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    target = _validate_target(str(args["target"]))
    depth = _bounded_int(
        args.get("depth"), default=5, minimum=1, maximum=10, name="depth"
    )
    max_candidates = _bounded_int(
        args.get("max_candidates"),
        default=100,
        minimum=1,
        maximum=_MAX_CANDIDATES,
        name="max_candidates",
    )
    timeout_sec = _bounded_int(
        args.get("timeout_sec"),
        default=600,
        minimum=30,
        maximum=7_200,
        name="timeout_sec",
    )

    katana_dir = ctx.scan_dir / "katana"
    katana_dir.mkdir(parents=True, exist_ok=True)
    urls_file = katana_dir / "katana_urls.txt"
    raw_log = ctx.raw_log_dir / "katana-crawl-web.log"

    cli = [
        "-u",
        target,
        "-d",
        str(depth),
        "-jc",
        "-ef",
        ",".join(_KATANA_EXCLUDED_EXTENSIONS),
        "-aff",
        "-o",
        str(urls_file),
        "-silent",
        "-no-color",
    ]

    binary, argv = _resolve_katana_binary(cli)
    started = time.monotonic()
    try:
        result = await run_command(
            binary=binary,
            args=argv,
            timeout_sec=timeout_sec,
            network=NetworkPolicy.REQUIRED,
            capture="file",
            raw_log_path=raw_log,
            cancel_token=ctx.cancel_token,
        )
    except SkillTimeout:
        return SkillResult(summary={"error": "timeout"}, raw_log_path=str(raw_log))
    except SkillCancelled:
        return SkillResult(summary={"cancelled": True}, raw_log_path=str(raw_log))
    except SkillBinaryMissing:
        raise

    summary = _parse_urls(urls_file, max_candidates, target)
    summary["elapsed_sec"] = round(time.monotonic() - started, 2)
    if result.exit_code != 0:
        summary.setdefault("error", f"exit={result.exit_code}")

    return SkillResult(summary=summary, raw_log_path=str(raw_log))

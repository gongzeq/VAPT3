"""sqlmap-detect handler.

Runs `sqlmap --batch` in detection-only mode against a single URL. Parses
the textual log for ``Parameter:`` / ``Type:`` / ``back-end DBMS:`` blocks.
Output directory (``--output-dir``) is confined to ``<scan_dir>/sqlmap``.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from secbot.skills._shared.runner import execute
from secbot.skills.types import (
    InvalidSkillArg,
    SkillBinaryMissing,
    SkillContext,
    SkillResult,
)


def _resolve_sqlmap_binary(cli: list[str]) -> tuple[str, list[str]]:
    """Return (binary, args) for sqlmap, honouring config overrides.

    Priority:
      1. Configured override in ``tools.skillBinaries.sqlmap``.
         The script is invoked **directly** (via its shebang) rather than
         through ``python3`` to avoid macOS TCC restrictions that may
         prevent the Homebrew Python interpreter from reading files in
         protected directories (Desktop / Documents / Downloads).
      2. ``sqlmap`` found on PATH.
      3. Raise :class:`SkillBinaryMissing` with a helpful hint.
    """
    from secbot.config.loader import load_config

    cfg = load_config()
    override = cfg.tools.skill_binaries.get("sqlmap")
    if override:
        if not Path(override).exists():
            raise SkillBinaryMissing(
                f"Configured sqlmap override not found: {override}. "
                "Check tools.skillBinaries.sqlmap in your config."
            )
        return override, cli
    if shutil.which("sqlmap"):
        return "sqlmap", cli
    raise SkillBinaryMissing(
        "sqlmap not found on PATH. "
        "Install sqlmap or set tools.skillBinaries.sqlmap in ~/.secbot/config.json"
    )

_PARAM_RE = re.compile(r"^Parameter:\s*(\S+)\s*\(([^)]+)\)", re.MULTILINE)
_TYPE_RE = re.compile(r"^\s*Type:\s*(.+)$", re.MULTILINE)
_TITLE_RE = re.compile(r"^\s*Title:\s*(.+)$", re.MULTILINE)
_PAYLOAD_RE = re.compile(r"^\s*Payload:\s*(.+)$", re.MULTILINE)
_DBMS_RE = re.compile(r"back-end DBMS:\s*(.+?)$", re.MULTILINE)
_SQLMAP_PARAM_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_NON_INJECTABLE_PARAM_NAMES = {
    "__eventvalidation",
    "__viewstate",
    "__viewstategenerator",
    "_csrf",
    "button",
    "btn",
    "csrf",
    "csrf_token",
    "csrfmiddlewaretoken",
    "submit",
    "token",
}


def _invocation_id(
    *,
    url: str,
    method: str,
    data: str | None,
    cookie: str | None,
) -> str:
    h = hashlib.sha256()
    for value in (method, url, data or "", cookie or ""):
        h.update(value.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()[:12]


def _reject_header_breaks(field: str, value: str | None) -> None:
    if value is not None and ("\r" in value or "\n" in value):
        raise InvalidSkillArg(f"{field} must not contain CR/LF")


def _parameter_names_from_pairs(pairs: list[tuple[str, str]]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for name, _value in pairs:
        if not name or not _SQLMAP_PARAM_RE.match(name):
            continue
        if name.lower() in _NON_INJECTABLE_PARAM_NAMES:
            continue
        if name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def _detectable_parameters(*, url: str, method: str, data: str | None) -> list[str]:
    """Return parameter names that sqlmap should explicitly test with ``-p``."""

    parts = urlsplit(url)
    if method == "POST" and data:
        return _parameter_names_from_pairs(parse_qsl(data, keep_blank_values=True))
    return _parameter_names_from_pairs(parse_qsl(parts.query, keep_blank_values=True))


def _write_request_file(
    *,
    sqlmap_dir: Path,
    url: str,
    method: str,
    data: str | None,
    cookie: str | None,
) -> tuple[Path, bool]:
    """Write a sqlmap ``-r`` request file and return (path, force_ssl).

    All parameter data (GET query string, POST body) is embedded in the
    request file itself so that no ``--data`` CLI argument is needed.
    This avoids triggering the sandbox ``FORBIDDEN_CHARS`` check on ``&``
    which is a legitimate HTTP form/query separator but a shell metachar.

    Combined with ``-p <name>`` on the CLI, sqlmap correctly identifies
    which parameters to test from the request file content.
    """

    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise InvalidSkillArg(f"invalid url: {url!r}")
    _reject_header_breaks("data", data)
    _reject_header_breaks("cookie", cookie)

    # Preserve query string in the request-line URL so that sqlmap can
    # parse GET parameters directly from the ``-r`` file without needing
    # a ``--data`` CLI argument (which would be blocked by the sandbox
    # FORBIDDEN_CHARS check when the query contains ``&``).
    target = parts.path or "/"
    if parts.query:
        target = f"{target}?{parts.query}"

    body = data if method == "POST" and data else ""
    body_bytes = body.encode("utf-8")
    headers = [
        f"{method} {target} HTTP/1.1",
        f"Host: {parts.netloc}",
        "User-Agent: secbot-sqlmap-detect/1.0",
        "Accept: */*",
        "Connection: close",
    ]
    if cookie:
        headers.append(f"Cookie: {cookie}")
    if method == "POST":
        headers.extend(
            [
                "Content-Type: application/x-www-form-urlencoded",
                f"Content-Length: {len(body_bytes)}",
            ]
        )

    request_file = sqlmap_dir / "request.txt"
    request_file.write_text("\r\n".join([*headers, "", body]), encoding="utf-8")
    return request_file, parts.scheme == "https"


def _parse(raw_log: Path, _exit_code: int) -> dict[str, Any]:
    text = ""
    if raw_log.exists():
        text = raw_log.read_text(encoding="utf-8", errors="replace")

    params: list[dict[str, Any]] = []
    # sqlmap prints blocks like:
    #   Parameter: id (GET)
    #       Type: boolean-based blind
    #       Title: AND boolean-based blind - WHERE or HAVING clause
    #       Payload: id=1 AND 1=1
    for m in _PARAM_RE.finditer(text):
        start = m.end()
        # take only 10 lines following the header
        block = "\n".join(text[start:].splitlines()[:12])
        type_m = _TYPE_RE.search(block)
        title_m = _TITLE_RE.search(block)
        payload_m = _PAYLOAD_RE.search(block)
        params.append(
            {
                "name": m.group(1),
                "place": m.group(2),
                "type": (type_m.group(1).strip() if type_m else ""),
                "title": (title_m.group(1).strip() if title_m else ""),
                "payload": (payload_m.group(1).strip()[:256] if payload_m else ""),
            }
        )

    dbms_m = _DBMS_RE.search(text)
    return {
        "vulnerable": bool(params),
        "parameters": params,
        "dbms": (dbms_m.group(1).strip() if dbms_m else ""),
    }


async def run(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    url: str = args["url"]
    method: str = args.get("method", "GET")
    data: str | None = args.get("data")
    cookie: str | None = args.get("cookie")
    level: int = int(args.get("level", 3))
    risk: int = int(args.get("risk", 1))

    # Auto-promote to POST when body data is provided without explicit method.
    # LLM agents frequently pass `data` without setting `method`, causing
    # sqlmap to receive a parameterless GET request and fail immediately.
    if data and method == "GET":
        method = "POST"

    parameters = _detectable_parameters(url=url, method=method, data=data)

    invocation_id = _invocation_id(url=url, method=method, data=data, cookie=cookie)
    sqlmap_dir = ctx.scan_dir / "sqlmap" / invocation_id
    sqlmap_dir.mkdir(parents=True, exist_ok=True)

    request_file, force_ssl = _write_request_file(
        sqlmap_dir=sqlmap_dir,
        url=url,
        method=method,
        data=data,
        cookie=cookie,
    )

    cli: list[str] = [
        "-r", str(request_file),
        "--batch",
        "--answers", "continue=y",
        "--disable-coloring",
        "--level", str(level),
        "--risk", str(risk),
        "--output-dir", str(sqlmap_dir),
        "--flush-session",
    ]
    if parameters:
        cli += ["-p", ",".join(parameters)]
    if force_ssl:
        cli.append("--force-ssl")

    binary, args = _resolve_sqlmap_binary(cli)
    return await execute(
        binary=binary,
        args=args,
        timeout_sec=900,
        raw_log_name=f"sqlmap-detect-{invocation_id}.log",
        ctx=ctx,
        parser=_parse,
    )

"""sqlmap-detect handler.

Runs `sqlmap --batch` in detection-only mode against a single URL. Parses
the textual log for ``Parameter:`` / ``Type:`` / ``back-end DBMS:`` blocks.
Output directory (``--output-dir``) is confined to ``<scan_dir>/sqlmap``.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from secbot.skills._shared.runner import execute
from secbot.skills.types import SkillBinaryMissing, SkillContext, SkillResult


def _resolve_sqlmap_binary(cli: list[str]) -> tuple[str, list[str]]:
    """Return (binary, args) for sqlmap, honouring config overrides.

    Priority:
      1. Configured override in ``tools.skillBinaries.sqlmap``.
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
        return "python3", [override] + cli
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
    level: int = int(args.get("level", 1))
    risk: int = int(args.get("risk", 1))

    sqlmap_dir = ctx.scan_dir / "sqlmap"
    sqlmap_dir.mkdir(parents=True, exist_ok=True)

    cli: list[str] = [
        "-u", url,
        "--batch",
        "--disable-coloring",
        "--level", str(level),
        "--risk", str(risk),
        "--output-dir", str(sqlmap_dir),
        "--flush-session",
    ]
    if method == "POST" and data:
        cli += ["--data", data]
    if cookie:
        cli += ["--cookie", cookie]

    binary, args = _resolve_sqlmap_binary(cli)
    return await execute(
        binary=binary,
        args=args,
        timeout_sec=900,
        raw_log_name="sqlmap-detect.log",
        ctx=ctx,
        parser=_parse,
    )

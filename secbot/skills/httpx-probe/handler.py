"""httpx-probe handler.

Invokes ``httpx -l <targets.txt> -json -silent`` and parses the JSONL output
into a structured service list. We explicitly prefer the ProjectDiscovery
binary; if PATH resolves to the Python ``httpx`` library shim (no
``-version`` / no ``projectdiscovery`` banner), the sandbox will still
attempt to run but the JSON parser will gracefully return an error record.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from secbot.skills._shared.runner import execute
from secbot.skills.types import InvalidSkillArg, SkillBinaryMissing, SkillContext, SkillResult


def _resolve_httpx_binary(cli: list[str]) -> tuple[str, list[str]]:
    """Return (binary, args) for httpx, honouring config overrides.

    Priority:
      1. Configured override in ``tools.skillBinaries.httpx``.
      2. ``httpx`` found on PATH.
      3. Raise :class:`SkillBinaryMissing` with a helpful hint.
    """
    import shutil

    from secbot.config.loader import load_config

    cfg = load_config()
    override = cfg.tools.skill_binaries.get("httpx")
    if override:
        if not Path(override).exists():
            raise SkillBinaryMissing(
                f"Configured httpx override not found: {override}. "
                "Check tools.skillBinaries.httpx in your config."
            )
        return override, cli
    if shutil.which("httpx"):
        return "httpx", cli
    raise SkillBinaryMissing(
        "httpx not found on PATH. "
        "Install projectdiscovery/httpx or set tools.skillBinaries.httpx in ~/.secbot/config.json"
    )


_TARGET_RE = re.compile(
    r"^https?://[a-zA-Z0-9._\-:/]+$"
    r"|^(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?$"
    r"|^[a-z0-9][a-z0-9.\-]*\.[a-z]{2,}(?::\d{1,5})?$"
)
_PORTSPEC_RE = re.compile(r"^[\d,\-]{1,128}$")


def _validate(targets: list[str], ports: str | None) -> None:
    for t in targets:
        if not isinstance(t, str) or not _TARGET_RE.match(t):
            raise InvalidSkillArg(f"invalid target: {t!r}")
    if ports and not _PORTSPEC_RE.match(ports):
        raise InvalidSkillArg(f"invalid port spec: {ports!r}")


def _parse(raw_log: Path, _exit_code: int) -> dict[str, Any]:
    services: list[dict[str, Any]] = []
    if not raw_log.exists():
        return {"services": services}

    with raw_log.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            services.append(
                {
                    "url": obj.get("url", ""),
                    "host": obj.get("host", ""),
                    "port": int(obj.get("port", 0)) or None,
                    "status_code": int(obj.get("status_code", 0)) or 0,
                    "title": obj.get("title", "") or "",
                    "tech": obj.get("tech", []) or [],
                    "server": obj.get("webserver", "") or "",
                    "content_length": int(obj.get("content_length", 0)) or 0,
                }
            )
    return {"services": services[:500]}


async def run(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    targets: list[str] = list(args["targets"])
    ports: str | None = args.get("ports")
    threads: int = int(args.get("threads", 25))
    follow_redirects: bool = bool(args.get("follow_redirects", False))

    _validate(targets, ports)

    targets_file = ctx.scan_dir / "httpx-targets.txt"
    targets_file.parent.mkdir(parents=True, exist_ok=True)
    targets_file.write_text("\n".join(targets) + "\n", encoding="utf-8")

    cli: list[str] = [
        "-l", str(targets_file),
        "-json",
        "-silent",
        "-no-color",
        "-threads", str(threads),
        "-tech-detect",
        "-title",
        "-status-code",
        "-server",
        "-content-length",
    ]
    if ports:
        cli += ["-ports", ports]
    if follow_redirects:
        cli.append("-follow-redirects")

    binary, args = _resolve_httpx_binary(cli)
    return await execute(
        binary=binary,
        args=args,
        timeout_sec=300,
        raw_log_name="httpx-probe.jsonl",
        ctx=ctx,
        parser=_parse,
    )

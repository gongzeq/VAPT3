"""fscan-port-scan handler."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from secbot.skills._shared.runner import execute, validate_portspec, validate_target
from secbot.skills.types import SkillContext, SkillResult

# fscan PortScan output: "10.0.0.5:22 open" / "10.0.0.5:80 open"
# service detection: "[*] WebTitle: http://10.0.0.5:80 ... [http]"
_OPEN_RE = re.compile(r"^([\d.]+):(\d+)\s+open", re.MULTILINE)


def _parse(raw_log: Path, exit_code: int) -> dict[str, Any]:
    if not raw_log.exists():
        return {"services": []}
    text = raw_log.read_text(encoding="utf-8", errors="replace")
    services: list[dict[str, Any]] = []
    for host, port in _OPEN_RE.findall(text):
        services.append(
            {"host": host, "port": int(port), "protocol": "tcp", "service": ""}
        )
        if len(services) >= 500:
            break
    return {"services": services}


async def run(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    target = args["target"]
    ports = args.get("ports", "1-65535")
    validate_target(target)
    validate_portspec(ports)

    return await execute(
        binary="fscan",
        args=["-h", target, "-p", ports, "-nopoc", "-nobr"],
        timeout_sec=900,
        raw_log_name="fscan-port-scan.log",
        ctx=ctx,
        parser=_parse,
    )

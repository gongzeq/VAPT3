"""nmap-port-scan handler."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from secbot.skills._shared.runner import execute, validate_portspec, validate_target
from secbot.skills.types import SkillContext, SkillResult

# nmap -oG: "Host: 10.0.0.1 ()  Ports: 22/open/tcp//ssh///, 80/open/tcp//http///"
_HOST_LINE = re.compile(r"^Host:\s+(\S+)\s+\(.*?\)\s+Ports:\s+(.+)$", re.MULTILINE)
_PORT_ENTRY = re.compile(r"(\d+)/open/(tcp|udp)//([^/]*)/")


def _parse(raw_log: Path, exit_code: int) -> dict[str, Any]:
    if not raw_log.exists():
        return {"services": []}
    text = raw_log.read_text(encoding="utf-8", errors="replace")
    services: list[dict[str, Any]] = []
    for host, ports_blob in _HOST_LINE.findall(text):
        for port, proto, service in _PORT_ENTRY.findall(ports_blob):
            services.append(
                {"host": host, "port": int(port), "protocol": proto, "service": service or ""}
            )
            if len(services) >= 500:
                return {"services": services}
    return {"services": services}


async def run(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    targets = args["targets"]
    ports = args.get("ports", "1-1024")

    for t in targets:
        validate_target(t)
    validate_portspec(ports)

    return await execute(
        binary="nmap",
        args=["-sS", "-Pn", "-oG", "-", "-p", ports, *targets],
        timeout_sec=600,
        raw_log_name="nmap-port-scan.log",
        ctx=ctx,
        parser=_parse,
    )

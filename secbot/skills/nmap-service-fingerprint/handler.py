"""nmap-service-fingerprint handler.

Runs ``nmap -sV`` and parses the greppable output to extract service /
product / version banners per host:port.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from secbot.skills._shared.runner import execute, validate_portspec, validate_target
from secbot.skills.types import SkillContext, SkillResult

# nmap -oG line format:
#   Host: 10.0.0.1 ()  Ports: 22/open/tcp//ssh//OpenSSH 8.2p1 Ubuntu///
_HOST_LINE = re.compile(r"^Host:\s+(\S+)\s+\(.*?\)\s+Ports:\s+(.+)$", re.MULTILINE)
# port/state/proto/owner/service/rpc_info/version/
_PORT_ENTRY = re.compile(r"(\d+)/open/(tcp|udp)//([^/]*)//([^/]*)/")


def _split_product_version(blob: str) -> tuple[str, str]:
    blob = blob.strip()
    if not blob:
        return "", ""
    # nmap often writes "<product> <version>"; last whitespace-separated token
    # with digits heuristically treated as version.
    parts = blob.rsplit(" ", 1)
    if len(parts) == 2 and any(ch.isdigit() for ch in parts[1]):
        return parts[0], parts[1]
    return blob, ""


def _parse(raw_log: Path, exit_code: int) -> dict[str, Any]:
    if not raw_log.exists():
        return {"services": []}
    text = raw_log.read_text(encoding="utf-8", errors="replace")
    services: list[dict[str, Any]] = []
    for host, ports_blob in _HOST_LINE.findall(text):
        for port, proto, service, version_blob in _PORT_ENTRY.findall(ports_blob):
            product, version = _split_product_version(version_blob)
            services.append(
                {
                    "host": host,
                    "port": int(port),
                    "protocol": proto,
                    "service": service or "",
                    "product": product,
                    "version": version,
                }
            )
            if len(services) >= 500:
                return {"services": services}
    return {"services": services}


async def run(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    targets: list[str] = args["targets"]
    ports: str = args["ports"]

    for t in targets:
        validate_target(t)
    validate_portspec(ports)

    return await execute(
        binary="nmap",
        args=["-sV", "-Pn", "-oG", "-", "-p", ports, *targets],
        timeout_sec=900,
        raw_log_name="nmap-service-fingerprint.log",
        ctx=ctx,
        parser=_parse,
    )

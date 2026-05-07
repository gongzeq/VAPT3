"""fscan-asset-discovery handler."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from secbot.skills._shared.runner import execute, validate_target
from secbot.skills.types import SkillContext, SkillResult

# fscan prints e.g.  "(icmp) Target 10.0.0.5  is alive"
_ALIVE_RE = re.compile(r"Target\s+([\d.]+)\s+is alive", re.IGNORECASE)


def _parse(raw_log: Path, exit_code: int) -> dict[str, Any]:
    if not raw_log.exists():
        return {"hosts_up": []}
    text = raw_log.read_text(encoding="utf-8", errors="replace")
    hosts = sorted(set(_ALIVE_RE.findall(text)))
    return {"hosts_up": hosts[:500]}


async def run(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    target = args["target"]
    validate_target(target)

    return await execute(
        binary="fscan",
        args=["-h", target, "-nopoc", "-nobr"],
        timeout_sec=300,
        raw_log_name="fscan-asset-discovery.log",
        ctx=ctx,
        parser=_parse,
    )

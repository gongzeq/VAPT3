"""nmap-host-discovery skill handler.

Spec: `.trellis/spec/backend/skill-contract.md`,
      `.trellis/spec/backend/tool-invocation-safety.md`.
"""

from __future__ import annotations

import re
import time
from typing import Any

from secbot.skills._shared import NetworkPolicy, run_command
from secbot.skills.types import (
    InvalidSkillArg,
    SkillBinaryMissing,
    SkillCancelled,
    SkillContext,
    SkillResult,
    SkillTimeout,
)

# Per-field allow-regex; runs BEFORE forbidden-char check in sandbox.
TARGET_PATTERN = re.compile(
    r"^(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?$"
    r"|^[a-z0-9][a-z0-9.\-]*\.[a-z]{2,}$"
    r"|^[a-fA-F0-9:]+(?:/\d{1,3})?$"  # IPv6
)

_RATE_TO_FLAG = {"slow": "-T2", "normal": "-T3", "fast": "-T4"}

_HOST_UP_RE = re.compile(r"^Host:\s+(\S+)\s+\(.*?\)\s+Status:\s+Up$", re.MULTILINE)


async def run(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    target = args["target"]
    rate = args.get("rate", "normal")

    if not TARGET_PATTERN.match(target):
        raise InvalidSkillArg(f"target {target!r} does not match TARGET_PATTERN")
    if rate not in _RATE_TO_FLAG:
        raise InvalidSkillArg(f"rate {rate!r} not in {sorted(_RATE_TO_FLAG)}")

    raw_log = ctx.raw_log_dir / "nmap-host-discovery.log"
    started = time.monotonic()

    try:
        result = await run_command(
            binary="nmap",
            args=["-sn", "-oG", "-", _RATE_TO_FLAG[rate], target],
            timeout_sec=120,
            network=NetworkPolicy.REQUIRED,
            capture="file",
            raw_log_path=raw_log,
            cancel_token=ctx.cancel_token,
        )
    except SkillTimeout:
        return SkillResult(summary={"hosts_up": [], "error": "timeout"}, raw_log_path=str(raw_log))
    except SkillCancelled:
        return SkillResult(summary={"hosts_up": [], "cancelled": True}, raw_log_path=str(raw_log))
    except SkillBinaryMissing:
        raise

    elapsed = round(time.monotonic() - started, 2)

    hosts_up: list[str] = []
    if result.exit_code == 0 and raw_log.exists():
        text = raw_log.read_text(encoding="utf-8", errors="replace")
        hosts_up = _HOST_UP_RE.findall(text)

    if result.exit_code != 0:
        return SkillResult(
            summary={"hosts_up": hosts_up, "error": f"exit={result.exit_code}", "elapsed_sec": elapsed},
            raw_log_path=str(raw_log),
        )

    return SkillResult(
        summary={"hosts_up": hosts_up[:200], "elapsed_sec": elapsed},
        raw_log_path=str(raw_log),
    )

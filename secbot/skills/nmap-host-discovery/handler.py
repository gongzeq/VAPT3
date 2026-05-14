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


def _resolve_nmap_binary(cli: list[str]) -> tuple[str, list[str]]:
    """Return (binary, args) for nmap, honouring config overrides.

    Priority:
      1. Configured override in ``tools.skillBinaries.nmap``.
      2. ``nmap`` found on PATH.
      3. Raise :class:`SkillBinaryMissing` with a helpful hint.
    """
    import shutil
    from pathlib import Path

    from secbot.config.loader import load_config

    cfg = load_config()
    override = cfg.tools.skill_binaries.get("nmap")
    if override:
        if not Path(override).exists():
            raise SkillBinaryMissing(
                f"Configured nmap override not found: {override}. "
                "Check tools.skillBinaries.nmap in your config."
            )
        return override, cli
    if shutil.which("nmap"):
        return "nmap", cli
    raise SkillBinaryMissing(
        "nmap not found on PATH. "
        "Install nmap or set tools.skillBinaries.nmap in ~/.secbot/config.json"
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

    binary, args = _resolve_nmap_binary(["-sn", "-oG", "-", _RATE_TO_FLAG[rate], target])
    try:
        result = await run_command(
            binary=binary,
            args=args,
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

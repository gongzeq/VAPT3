"""qscan-host-discovery skill handler.

Spec: `.trellis/spec/backend/skill-contract.md`,
      `.trellis/spec/backend/tool-invocation-safety.md`.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
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


def _resolve_qscan_binary(cli: list[str]) -> tuple[str, list[str]]:
    """Return (binary, args) for qscan, honouring config overrides.

    Priority:
      1. Configured override in ``tools.skillBinaries.qscan``.
      2. ``qscan`` found on PATH.
      3. Raise :class:`SkillBinaryMissing` with a helpful hint.
    """
    import shutil

    from secbot.config.loader import load_config

    cfg = load_config()
    override = cfg.tools.skill_binaries.get("qscan")
    if override:
        if not Path(override).exists():
            raise SkillBinaryMissing(
                f"Configured qscan override not found: {override}. "
                "Check tools.skillBinaries.qscan in your config."
            )
        return override, cli
    if shutil.which("qscan"):
        return "qscan", cli
    raise SkillBinaryMissing(
        "qscan not found on PATH. "
        "Install qscan or set tools.skillBinaries.qscan in ~/.secbot/config.json"
    )


# Per-field allow-regex; runs BEFORE forbidden-char check in sandbox.
TARGET_PATTERN = re.compile(
    r"^(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?$"
    r"|^[a-z0-9][a-z0-9.\-]*\.[a-z]{2,}$"
    r"|^[a-fA-F0-9:]+(?:/\d{1,3})?$"  # IPv6
)

# Extract host from qscan output lines.
_HOST_RE = re.compile(
    r"^(?:https?://)?((?:\d{1,3}\.){3}\d{1,3}|"
    r"[a-z0-9][a-z0-9.\-]*\.[a-z]{2,}|"
    r"[a-fA-F0-9:]+)",
    re.IGNORECASE,
)


async def run(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    target = args["target"]

    if not TARGET_PATTERN.match(target):
        raise InvalidSkillArg(f"target {target!r} does not match TARGET_PATTERN")

    raw_log = ctx.raw_log_path("qscan-host-discovery.log")
    raw_log.write_bytes(b"")
    started = time.monotonic()

    binary, cmd_args = _resolve_qscan_binary(["-t", target, "-o", str(raw_log)])
    try:
        result = await run_command(
            binary=binary,
            args=cmd_args,
            timeout_sec=120,
            network=NetworkPolicy.REQUIRED,
            capture="discard",
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
        for line in text.splitlines():
            m = _HOST_RE.match(line.strip())
            if m:
                hosts_up.append(m.group(1))

    if result.exit_code != 0:
        return SkillResult(
            summary={"hosts_up": hosts_up, "error": f"exit={result.exit_code}", "elapsed_sec": elapsed},
            raw_log_path=str(raw_log),
        )

    return SkillResult(
        summary={"hosts_up": hosts_up[:200], "elapsed_sec": elapsed},
        raw_log_path=str(raw_log),
    )

"""fscan-asset-discovery handler."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from secbot.skills._shared.runner import execute, validate_target
from secbot.skills.types import SkillBinaryMissing, SkillContext, SkillResult


def _resolve_fscan_binary(cli: list[str]) -> tuple[str, list[str]]:
    """Return (binary, args) for fscan, honouring config overrides.

    Priority:
      1. Configured override in ``tools.skillBinaries.fscan``.
      2. ``fscan`` found on PATH.
      3. Raise :class:`SkillBinaryMissing` with a helpful hint.
    """
    import shutil
    from pathlib import Path

    from secbot.config.loader import load_config

    cfg = load_config()
    override = cfg.tools.skill_binaries.get("fscan")
    if override:
        if not Path(override).exists():
            raise SkillBinaryMissing(
                f"Configured fscan override not found: {override}. "
                "Check tools.skillBinaries.fscan in your config."
            )
        return override, cli
    if shutil.which("fscan"):
        return "fscan", cli
    raise SkillBinaryMissing(
        "fscan not found on PATH. "
        "Install fscan or set tools.skillBinaries.fscan in ~/.secbot/config.json"
    )


# fscan prints e.g.  "(icmp) Target 10.0.0.5  is alive""
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

    binary, args = _resolve_fscan_binary(["-h", target, "-nopoc", "-nobr"])
    return await execute(
        binary=binary,
        args=args,
        timeout_sec=300,
        raw_log_name="fscan-asset-discovery.log",
        ctx=ctx,
        parser=_parse,
    )

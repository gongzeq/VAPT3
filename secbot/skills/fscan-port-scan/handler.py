"""fscan-port-scan handler."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from secbot.skills._shared.runner import execute, validate_portspec, validate_target
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

    binary, args = _resolve_fscan_binary(["-h", target, "-p", ports, "-nopoc", "-nobr"])
    return await execute(
        binary=binary,
        args=args,
        timeout_sec=900,
        raw_log_name="fscan-port-scan.log",
        ctx=ctx,
        parser=_parse,
    )

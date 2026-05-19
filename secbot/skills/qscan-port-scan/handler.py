"""qscan-port-scan handler."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from secbot.skills._shared import NetworkPolicy, run_command
from secbot.skills._shared.runner import validate_target
from secbot.skills.types import (
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


# qscan output example:
# http://112.124.30.49/  Title  Port:80,FingerPrint:Perl;HTML5,Digest:...,Length:2567
_PORT_RE = re.compile(r"Port:(\d+)")
_FP_RE = re.compile(r"FingerPrint:([^,]+)")
_HOST_RE = re.compile(
    r"^(?:https?://)?((?:\d{1,3}\.){3}\d{1,3}|"
    r"[a-z0-9][a-z0-9.\-]*\.[a-z]{2,}|"
    r"[a-fA-F0-9:]+)",
    re.IGNORECASE,
)


def _parse(
    raw_log: Path, exit_code: int
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not raw_log.exists():
        return {"services": []}, []
    text = raw_log.read_text(encoding="utf-8", errors="replace")
    services: list[dict[str, Any]] = []
    cmdb_writes: list[dict[str, Any]] = []
    for line in text.splitlines():
        port_m = _PORT_RE.search(line)
        if not port_m:
            continue
        port = int(port_m.group(1))
        host_m = _HOST_RE.match(line.strip())
        host = host_m.group(1) if host_m else ""
        fp_m = _FP_RE.search(line)
        fingerprint = fp_m.group(1) if fp_m else ""
        services.append(
            {"host": host, "port": port, "protocol": "tcp", "service": fingerprint}
        )
        cmdb_writes.append(
            {
                "table": "services",
                "op": "upsert",
                "data": {
                    "target": host,
                    "port": port,
                    "protocol": "tcp",
                    "state": "open",
                    "service": fingerprint,
                },
            }
        )
        if len(services) >= 500:
            return {"services": services}, cmdb_writes
    return {"services": services}, cmdb_writes


async def run(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    target = args["target"]
    ports = args.get("ports")

    validate_target(target)

    raw_log = ctx.raw_log_dir / "qscan-port-scan.log"
    started = time.monotonic()

    if ports:
        binary, cmd_args = _resolve_qscan_binary(
            ["-t", target, "-p", ports, "-o", str(raw_log)]
        )
    else:
        binary, cmd_args = _resolve_qscan_binary(
            ["-t", target, "--top", "1000", "-o", str(raw_log)]
        )

    try:
        result = await run_command(
            binary=binary,
            args=cmd_args,
            timeout_sec=600,
            network=NetworkPolicy.REQUIRED,
            capture="discard",
            cancel_token=ctx.cancel_token,
        )
    except SkillTimeout:
        return SkillResult(
            summary={"services": [], "error": "timeout"}, raw_log_path=str(raw_log)
        )
    except SkillCancelled:
        return SkillResult(
            summary={"services": [], "cancelled": True}, raw_log_path=str(raw_log)
        )
    except SkillBinaryMissing:
        raise

    elapsed = round(time.monotonic() - started, 2)

    parsed, cmdb_writes = _parse(raw_log, result.exit_code)
    parsed.setdefault("elapsed_sec", elapsed)
    if result.exit_code != 0:
        parsed.setdefault("error", f"exit={result.exit_code}")

    return SkillResult(
        summary=parsed,
        raw_log_path=str(raw_log),
        cmdb_writes=cmdb_writes,
    )

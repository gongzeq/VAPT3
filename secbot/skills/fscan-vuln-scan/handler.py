"""fscan-vuln-scan handler.

Runs fscan with default POC checks, parses the textual log for
[+] vuln-style hits, and emits findings + cmdb writes.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from secbot.skills._shared import NetworkPolicy, run_command
from secbot.skills._shared.resource import resolve_resource
from secbot.skills._shared.runner import validate_portspec, validate_target
from secbot.skills.types import (
    InvalidSkillArg,
    SkillBinaryMissing,
    SkillCancelled,
    SkillContext,
    SkillResult,
    SkillTimeout,
)


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

# Lines look like: "[+] poc-yaml-xxx http://1.2.3.4:80 ..."
_VULN_RE = re.compile(
    r"^\[\+\]\s+(?P<title>[\w\-./]+)\s+(?P<url>https?://[^\s]+)",
    re.MULTILINE,
)
_HOSTPORT_RE = re.compile(
    r"^(?P<host>[\w.\-]+)(?::(?P<port>\d+))?",
)
_MAX_FINDINGS = 1000


def _parse(raw_log: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    writes: list[dict[str, Any]] = []
    if not raw_log.exists():
        return findings, writes
    text = raw_log.read_text(encoding="utf-8", errors="replace")
    for m in _VULN_RE.finditer(text):
        title = m.group("title")
        url = m.group("url")
        # strip scheme://
        netloc = url.split("://", 1)[1].split("/", 1)[0]
        hp = _HOSTPORT_RE.match(netloc)
        host = hp.group("host") if hp else netloc
        port_str = hp.group("port") if hp else None
        port = int(port_str) if port_str and port_str.isdigit() else 0
        finding = {
            "host": host,
            "port": port,
            "title": title,
            "severity": "high",
        }
        findings.append(finding)
        writes.append(
            {
                "table": "vulnerabilities",
                "op": "upsert",
                "data": {
                    "template_id": title,
                    "severity": "high",
                    "target": host,
                    "evidence": url[:512],
                    "title": title[:256],
                },
            }
        )
        if len(findings) >= _MAX_FINDINGS:
            break
    return findings, writes


async def run(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    target = args["target"]
    ports = args.get("ports", "80,443,8080,8443")
    user_dict = args.get("user_dict")
    pass_dict = args.get("pass_dict")
    validate_target(target)
    validate_portspec(ports)

    raw_log = ctx.raw_log_dir / "fscan-vuln-scan.log"
    started = time.monotonic()

    cli = ["-h", target, "-p", ports, "-o", str(raw_log)]
    binary, args = _resolve_fscan_binary(cli)

    # Enable brute-force when wordlists are provided; otherwise keep POC-only.
    if not user_dict and not pass_dict:
        cli.append("-nobr")

    if user_dict:
        p = resolve_resource(ctx, "fuzzDicts", user_dict)
        if p is None:
            raise InvalidSkillArg(f"user_dict not found in fuzzDicts: {user_dict}")
        cli += ["-userf", str(p)]

    if pass_dict:
        p = resolve_resource(ctx, "fuzzDicts", pass_dict)
        if p is None:
            raise InvalidSkillArg(f"pass_dict not found in fuzzDicts: {pass_dict}")
        cli += ["-pwdf", str(p)]

    try:
        result = await run_command(
            binary=binary,
            args=args,
            timeout_sec=900,
            network=NetworkPolicy.REQUIRED,
            capture="discard",
            cancel_token=ctx.cancel_token,
        )
    except SkillTimeout:
        return SkillResult(summary={"error": "timeout"}, raw_log_path=str(raw_log))
    except SkillCancelled:
        return SkillResult(summary={"cancelled": True}, raw_log_path=str(raw_log))
    except SkillBinaryMissing:
        raise

    elapsed = round(time.monotonic() - started, 2)
    findings, writes = _parse(raw_log)

    summary: dict[str, Any] = {
        "findings_count": len(findings),
        "elapsed_sec": elapsed,
    }
    if result.exit_code != 0 and not findings:
        summary["error"] = f"exit={result.exit_code}"

    return SkillResult(
        summary=summary,
        raw_log_path=str(raw_log),
        findings=findings,
        cmdb_writes=writes,
    )

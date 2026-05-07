"""nuclei-template-scan handler.

Runs nuclei with a curated severity/tag filter, parses the JSONL output,
and emits structured findings + cmdb writes.
"""

from __future__ import annotations

import json
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

_TARGET_RE = re.compile(
    r"^https?://[a-zA-Z0-9._\-:/]+$"
    r"|^(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?$"
    r"|^[a-z0-9][a-z0-9.\-]*\.[a-z]{2,}(?::\d{1,5})?$"
)
_TAGS_RE = re.compile(r"^[a-zA-Z0-9,_\-]*$")
_SEVERITY_ALLOWED = {"medium,high,critical", "high,critical", "critical"}

_MAX_FINDINGS = 1000


def _validate(targets: list[str], severity: str, tags: str) -> None:
    if not targets:
        raise InvalidSkillArg("targets must not be empty")
    if len(targets) > 256:
        raise InvalidSkillArg("targets exceeds 256")
    for t in targets:
        if not isinstance(t, str) or not _TARGET_RE.match(t):
            raise InvalidSkillArg(f"invalid target: {t!r}")
    if severity not in _SEVERITY_ALLOWED:
        raise InvalidSkillArg(f"invalid severity: {severity!r}")
    if not _TAGS_RE.match(tags):
        raise InvalidSkillArg(f"invalid tags: {tags!r}")


def _parse(raw_log: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    cmdb_writes: list[dict[str, Any]] = []
    if not raw_log.exists():
        return findings, cmdb_writes

    with raw_log.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            tpl = obj.get("template-id") or obj.get("templateID") or ""
            info = obj.get("info") or {}
            severity = (info.get("severity") or "info").lower()
            host = obj.get("host") or obj.get("matched-at") or ""
            matched_at = obj.get("matched-at") or ""
            name = info.get("name") or ""
            findings.append(
                {
                    "template_id": tpl,
                    "severity": severity,
                    "host": host,
                    "matched_at": matched_at,
                    "name": name,
                }
            )
            cmdb_writes.append(
                {
                    "table": "vulnerabilities",
                    "op": "upsert",
                    "data": {
                        "template_id": tpl,
                        "severity": severity,
                        "target": host,
                        "evidence": matched_at[:512],
                        "title": name[:256],
                    },
                }
            )
            if len(findings) >= _MAX_FINDINGS:
                break
    return findings, cmdb_writes


async def run(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    targets: list[str] = list(args["targets"])
    severity: str = args.get("severity", "medium,high,critical")
    tags: str = args.get("tags", "cve,exposure,misconfig")

    _validate(targets, severity, tags)

    raw_log = ctx.raw_log_dir / "nuclei.jsonl"
    targets_file = ctx.scan_dir / "nuclei-targets.txt"
    targets_file.parent.mkdir(parents=True, exist_ok=True)
    targets_file.write_text("\n".join(targets) + "\n", encoding="utf-8")

    started = time.monotonic()
    cli_args = [
        "-l", str(targets_file),
        "-severity", severity,
        "-tags", tags,
        "-jsonl",
        "-silent",
        "-no-color",
        "-disable-update-check",
        "-o", str(raw_log),
    ]

    try:
        result = await run_command(
            binary="nuclei",
            args=cli_args,
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
    findings, cmdb_writes = _parse(raw_log)

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
        cmdb_writes=cmdb_writes,
    )

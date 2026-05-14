"""Common skill execution helpers."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from secbot.skills._shared import NetworkPolicy, run_command
from secbot.skills.types import (
    InvalidSkillArg,
    SkillBinaryMissing,
    SkillCancelled,
    SkillContext,
    SkillResult,
    SkillTimeout,
)

TARGET_RE = re.compile(
    r"^(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?$"
    r"|^[a-z0-9][a-z0-9.\-]*\.[a-z]{2,}$"
)

PORTSPEC_RE = re.compile(r"^[\d,\-]{1,128}$")


def validate_target(target: str) -> None:
    if not isinstance(target, str) or not TARGET_RE.match(target):
        raise InvalidSkillArg(f"invalid target: {target!r}")


def validate_portspec(spec: str) -> None:
    if not PORTSPEC_RE.match(spec):
        raise InvalidSkillArg(f"invalid port spec: {spec!r}")


async def execute(
    *,
    binary: str,
    args: Sequence[str],
    timeout_sec: int,
    raw_log_name: str,
    ctx: SkillContext,
    network: NetworkPolicy = NetworkPolicy.REQUIRED,
    parser: Optional[
        Callable[[Path, int], dict[str, Any] | tuple[dict[str, Any], list[dict[str, Any]]]]
    ] = None,
) -> SkillResult:
    """Run *binary* via the sandbox; on success delegate to *parser*.

    *parser* may return either a plain summary dict, or a ``(summary,
    cmdb_writes)`` tuple so the skill can declaratively persist scan results.
    """
    raw_log = ctx.raw_log_dir / raw_log_name
    started = time.monotonic()

    try:
        result = await run_command(
            binary=binary,
            args=list(args),
            timeout_sec=timeout_sec,
            network=network,
            capture="file",
            raw_log_path=raw_log,
            cancel_token=ctx.cancel_token,
        )
    except SkillTimeout:
        return SkillResult(summary={"error": "timeout"}, raw_log_path=str(raw_log))
    except SkillCancelled:
        return SkillResult(summary={"cancelled": True}, raw_log_path=str(raw_log))
    except SkillBinaryMissing:
        raise

    elapsed = round(time.monotonic() - started, 2)

    parsed: dict[str, Any] = {}
    cmdb_writes: list[dict[str, Any]] = []
    if parser is not None:
        try:
            parser_result = parser(raw_log, result.exit_code)
            if isinstance(parser_result, tuple):
                parsed, cmdb_writes = parser_result
            else:
                parsed = parser_result
        except Exception as exc:  # noqa: BLE001
            parsed = {"parse_error": str(exc)[:200]}

    parsed.setdefault("elapsed_sec", elapsed)
    if result.exit_code != 0:
        parsed.setdefault("error", f"exit={result.exit_code}")

    return SkillResult(summary=parsed, raw_log_path=str(raw_log), cmdb_writes=cmdb_writes)

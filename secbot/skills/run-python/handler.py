"""run-python handler.

Execute a short one-shot Python 3 script written by the LLM. The script is
archived under ``<scan_dir>/run-python/<timestamp>.py`` and launched through
the secbot sandbox as ``python3 -I -B <script>``. stdout/stderr (merged) is
streamed to ``<scan_dir>/raw/run-python-<timestamp>.log`` and the tail (≤10 KB)
is returned to the LLM.

Spec: ``.trellis/spec/backend/skill-contract.md`` +
``.trellis/spec/backend/tool-invocation-safety.md``. ``risk_level: critical``
so ``HighRiskGate`` will block on ``ctx.confirm`` before the first call of the
conversation.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from secbot.skills._shared import NetworkPolicy
from secbot.skills._shared.runner import execute
from secbot.skills.types import InvalidSkillArg, SkillContext, SkillResult

# Tail size returned to the LLM. Raw log on disk is kept in full.
_STDOUT_TAIL_BYTES = 10 * 1024

# Defence-in-depth: input.schema.json already enforces these, but we re-check
# at the handler boundary in case a caller bypassed JSON Schema validation.
_MAX_CODE_BYTES = 32 * 1024
_DEFAULT_TIMEOUT_SEC = 60
_MAX_TIMEOUT_SEC = 600


def _read_tail(path: Path, cap: int) -> tuple[str, int, bool]:
    """Return (text_tail, total_bytes, truncated) for ``path``."""
    if not path.exists():
        return "", 0, False
    total = path.stat().st_size
    with path.open("rb") as fh:
        if total > cap:
            fh.seek(total - cap)
            raw = fh.read()
            truncated = True
        else:
            raw = fh.read()
            truncated = False
    return raw.decode("utf-8", errors="replace"), total, truncated


async def run(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    code = args.get("code")
    if not isinstance(code, str) or not code:
        raise InvalidSkillArg("'code' must be a non-empty string")
    # JSON Schema already enforces this via maxLength, but the schema counts
    # characters while the spec budget is in bytes; recheck in UTF-8.
    encoded = code.encode("utf-8")
    if len(encoded) > _MAX_CODE_BYTES:
        raise InvalidSkillArg(
            f"'code' exceeds {_MAX_CODE_BYTES} bytes (got {len(encoded)})"
        )

    timeout_sec = int(args.get("timeout_sec") or _DEFAULT_TIMEOUT_SEC)
    if timeout_sec < 1 or timeout_sec > _MAX_TIMEOUT_SEC:
        raise InvalidSkillArg(
            f"'timeout_sec' must be in [1,{_MAX_TIMEOUT_SEC}] (got {timeout_sec})"
        )

    # Archive the script source so runs are reproducible / auditable.
    script_dir = ctx.scan_dir / "run-python"
    script_dir.mkdir(parents=True, exist_ok=True)
    ts_ms = int(time.time() * 1000)
    script_path = script_dir / f"{ts_ms}.py"
    script_path.write_bytes(encoded)

    raw_log_name = f"run-python-{ts_ms}.log"

    def _parse(raw_log: Path, exit_code: int) -> dict[str, Any]:
        tail, total, truncated = _read_tail(raw_log, _STDOUT_TAIL_BYTES)
        summary: dict[str, Any] = {
            "exit_code": exit_code,
            "stdout_tail": tail,
            "bytes": total,
            "truncated": truncated,
            "script_path": str(script_path),
        }
        return summary

    # ``python3 -I`` isolates the interpreter (ignores PYTHON* env, user
    # site-packages, and doesn't add the script's dir to sys.path implicitly
    # beyond what -B asks for). ``-B`` suppresses .pyc writes.
    return await execute(
        binary="python3",
        args=["-I", "-B", str(script_path)],
        timeout_sec=timeout_sec,
        raw_log_name=raw_log_name,
        ctx=ctx,
        network=NetworkPolicy.REQUIRED,
        parser=_parse,
    )

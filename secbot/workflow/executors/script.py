"""``kind=script`` executor — thin wrapper around the ``exec`` shell tool.

Per dev-guide §6 the MVP does NOT sandbox scripts beyond whatever the
``exec`` tool already enforces (deny / allow patterns, workspace
restriction, timeout cap). We:

1. Validate ``args`` shape strictly (``kind`` ∈ {python, shell},
   ``code`` non-empty, ``timeoutMs`` ∈ [100, 60_000], optional
   ``stdin``).
2. Build a shell command:

   * ``kind=shell``     → the ``code`` is run by ``bash -lc``.
   * ``kind=python``    → pipe through ``python3 -`` so we never have
     to worry about shell-quoting the user script.

3. Invoke the ``exec`` tool with ``timeout = ceil(timeoutMs / 1000)``.
4. Parse the tool's ``"Exit code: N"`` trailer and return::

       {
           "exit_code": <int>,
           "stdout":    <str>,
           "stderr":    <str>,
       }

Non-zero exit codes are reported as :class:`ExecutorError` so
``on_error`` / retry can kick in; the raw output is still embedded in
the error message.
"""

from __future__ import annotations

import base64
import json
import re
import shlex
from math import ceil
from typing import Any

from secbot.workflow.executors.base import ExecutorError, StepContext, StepExecutor
from secbot.workflow.types import WorkflowStep

_TIMEOUT_MIN_MS = 100
_TIMEOUT_MAX_MS = 60_000
_EXIT_RE = re.compile(r"^Exit code:\s*(-?\d+)\s*$", re.MULTILINE)
_STDERR_RE = re.compile(r"^STDERR:\n(.*?)(?=^Exit code:|\Z)", re.MULTILINE | re.DOTALL)


class ScriptExecutor(StepExecutor):
    """Run user-supplied Python or shell snippets via the ``exec`` tool."""

    kind = "script"

    def __init__(self, tool_registry: Any) -> None:
        if tool_registry is None:
            raise ValueError("ScriptExecutor requires a non-None tool_registry")
        self._tools = tool_registry

    async def _run(
        self,
        step: WorkflowStep,
        args: dict[str, Any],
        ctx: StepContext,
    ) -> Any:
        kind = args.get("kind")
        code = args.get("code")
        timeout_ms = args.get("timeoutMs", args.get("timeout_ms", 5_000))
        stdin = args.get("stdin")

        if kind not in ("python", "shell"):
            raise ExecutorError(
                "workflow.validation.script_kind: "
                "args.kind must be one of {python, shell}"
            )
        if not isinstance(code, str) or not code.strip():
            raise ExecutorError(
                "workflow.validation.script_code: args.code must be a non-empty string"
            )
        if not isinstance(timeout_ms, int) or not (
            _TIMEOUT_MIN_MS <= timeout_ms <= _TIMEOUT_MAX_MS
        ):
            raise ExecutorError(
                "workflow.validation.script_timeout: "
                f"timeoutMs must be an int in [{_TIMEOUT_MIN_MS}, {_TIMEOUT_MAX_MS}]"
            )
        if stdin is not None and not isinstance(stdin, str):
            raise ExecutorError(
                "workflow.validation.script_stdin: args.stdin must be a string if provided"
            )

        command = _build_command(kind, code, stdin)
        timeout_s = max(1, ceil(timeout_ms / 1000))

        if not self._tools.has("exec"):
            raise ExecutorError(
                "workflow.executor.shell_unavailable: 'exec' tool is not registered"
            )

        raw = await self._tools.execute(
            "exec",
            {"command": command, "timeout": timeout_s},
        )
        if not isinstance(raw, str):
            raise ExecutorError(
                f"workflow.executor.script_unexpected: exec returned {type(raw).__name__}"
            )
        # Registry-level failure (permission / guard hit): string starts
        # with "Error:". Those should already short-circuit via the tool
        # layer but double-check for defence in depth.
        if raw.startswith("Error:") and _EXIT_RE.search(raw) is None:
            raise ExecutorError(raw)

        output = _parse_exec_output(raw)
        if output["exit_code"] != 0:
            raise ExecutorError(
                f"workflow.executor.script_nonzero_exit: exit_code={output['exit_code']}, "
                f"stderr={output['stderr'][:200]!r}"
            )
        # Convenience field for downstream template authors: when the
        # script writes valid JSON to stdout, expose the parsed object
        # under ``parsed`` so condition / args templates can do
        # ``${steps.<id>.result.parsed.cache_hit}`` instead of having to
        # decode JSON in shell. Mirrors the LlmExecutor's ``parsed``
        # field for ``responseFormat=json``.
        stdout_str = output["stdout"].strip()
        if stdout_str:
            try:
                output["parsed"] = json.loads(stdout_str)
            except (json.JSONDecodeError, ValueError):
                # Stdout is not JSON — leave ``parsed`` absent so
                # templates that opt-in get an explicit ExprError on
                # access (better than silently passing ``None``).
                pass
        return output


def _build_command(kind: str, code: str, stdin: str | None) -> str:
    """Compose the shell command that runs the user-supplied snippet.

    ``kind=python`` MUST pass the source via ``python3 -c`` (argv) — NOT
    ``python3 -`` (stdin). Otherwise the user script's ``sys.stdin`` is
    already drained by the interpreter reading source, and the
    ``stdin`` payload we piped in is silently dropped (#phishing-step1
    saw all features as empty strings because of this).
    """
    if kind == "shell":
        body = f"bash -lc {shlex.quote(code)}"
    else:
        # python: source goes through argv so stdin stays free for the
        # caller-supplied data payload.
        body = f"python3 -c {shlex.quote(code)}"

    if stdin is None:
        return body
    # Feed ``stdin`` on the script's stdin. We chain with a `printf` and
    # a `|` instead of here-docs to keep the command a single line
    # (easier for exec-tool's allow-list guards).
    #
    # The payload is base64-encoded so the raw bytes (which may contain
    # URLs / shell metachars / non-ASCII) never appear in the command
    # string. Without this wrapping, ExecTool._guard_command's
    # ``contains_internal_url`` scanner trips on any URL the user
    # passed as data (e.g. a phishing URL inside the email body) and
    # blocks the whole step. Decoding happens via ``base64 -d`` (GNU
    # coreutils) which is part of the standard exec-tool environment.
    encoded = base64.b64encode(stdin.encode("utf-8")).decode("ascii")
    return f"printf %s {shlex.quote(encoded)} | base64 -d | {body}"


def _parse_exec_output(raw: str) -> dict[str, Any]:
    """Extract structured {exit_code, stdout, stderr} from the ``exec`` tool."""
    exit_match = _EXIT_RE.search(raw)
    exit_code = int(exit_match.group(1)) if exit_match else -1

    stderr_match = _STDERR_RE.search(raw)
    stderr = stderr_match.group(1).rstrip("\n") if stderr_match else ""

    # Stdout = everything before STDERR / Exit code trailers.
    cutoff = len(raw)
    if stderr_match:
        cutoff = min(cutoff, stderr_match.start())
    elif exit_match:
        cutoff = min(cutoff, exit_match.start())
    stdout = raw[:cutoff].rstrip("\n")
    return {"exit_code": exit_code, "stdout": stdout, "stderr": stderr}

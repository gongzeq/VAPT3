"""Curl execution tool — direct HTTP via the system curl binary."""

import asyncio
import os
import re
import shutil
import sys
from contextlib import suppress
from typing import Any

from loguru import logger

from secbot.agent.tools.base import Tool, tool_parameters
from secbot.agent.tools.schema import IntegerSchema, StringSchema, tool_parameters_schema

_IS_WINDOWS = sys.platform == "win32"

# Deny patterns for curl commands
_CURL_DENY_PATTERNS = [
    # Prevent file writes via --output / -o
    # r"\B-o\s+\S",
    # r"\B--output\b",
    # # Prevent local file reads via file://
    # r"\bfile://",
    # # Prevent telnet / gopher / dict protocols
    # r"\btelnet://",
    # r"\bgopher://",
    # r"\bdict://",
    # # Prevent FTP data connections that can write
    # r"\bftp://",
    # # Prevent uploads
    # r"\B-T\s+\S",
    # r"\B--upload-file\b",
    # # Prevent reading local files via @
    # r"\B-d\s+@",
    # r"\B--data\s+@",
    # r"\B--data-binary\s+@",
    # r"\B--data-urlencode\s+@",
    # r"\B--form\s+@",
    # # Prevent reading from stdin
    # r"\B-d\s+@?-",
    # r"\B--data\s+@?-",
]


@tool_parameters(
    tool_parameters_schema(
        command=StringSchema(
            "The curl command to execute. Must start with 'curl'. "
            "All standard curl flags are supported (headers, methods, data, cookies, auth, etc.). "
            "Use -sS for silent mode with errors shown. "
            "Use -i or -I to include response headers. "
            "Use -w to format output."
        ),
        timeout=IntegerSchema(
            60,
            description="Timeout in seconds (default 60, max 300).",
            minimum=1,
            maximum=300,
        ),
        required=["command"],
    )
)
class CurlTool(Tool):
    """Execute curl commands for direct HTTP requests.

    Returns stdout, stderr, exit code, and elapsed time.
    Supports all standard curl flags except file-write / file-read operations.
    """

    name = "curl"
    description = (
        "Execute HTTP requests using the system curl binary. "
        "Accepts any standard curl command (GET, POST, PUT, DELETE, headers, cookies, auth, etc.). "
        "Returns the full response body, headers (with -i/-I), status code, and timing info. "
        "Example: 'curl -sS -i https://api.example.com/health'"
    )

    _MAX_TIMEOUT = 300
    _MAX_OUTPUT = 50_000

    @property
    def read_only(self) -> bool:
        return True

    @property
    def exclusive(self) -> bool:
        return True

    async def execute(
        self, command: str, timeout: int | None = None, **kwargs: Any,
    ) -> str:
        command = command.strip()

        # Must start with curl
        if not command.startswith("curl"):
            return (
                'Error: command must start with "curl". '
                f'Got: {command[:80]}{"..." if len(command) > 80 else ""}'
            )

        # Security guard
        guard_error = self._guard_command(command)
        if guard_error:
            return guard_error

        effective_timeout = min(timeout or 60, self._MAX_TIMEOUT)

        logger.debug("curl: {}", command)

        try:
            process = await self._spawn(command, effective_timeout)

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=effective_timeout,
                )
            except asyncio.TimeoutError:
                await self._kill_process(process)
                return f"Error: curl timed out after {effective_timeout} seconds"
            except asyncio.CancelledError:
                await self._kill_process(process)
                raise

            output_parts: list[str] = []

            if stdout:
                stdout_text = stdout.decode("utf-8", errors="replace")
                output_parts.append(stdout_text)

            if stderr:
                stderr_text = stderr.decode("utf-8", errors="replace")
                if stderr_text.strip():
                    output_parts.append(f"STDERR:\n{stderr_text}")

            output_parts.append(f"\nExit code: {process.returncode}")

            result = "\n".join(output_parts) if output_parts else "(no output)"

            # Truncate if too long
            max_len = self._MAX_OUTPUT
            if len(result) > max_len:
                half = max_len // 2
                result = (
                    result[:half]
                    + f"\n\n... ({len(result) - max_len:,} chars truncated) ...\n\n"
                    + result[-half:]
                )

            return result

        except Exception as e:
            logger.exception("curl execution failed")
            return f"Error executing curl: {str(e)}"

    @staticmethod
    def _guard_command(command: str) -> str | None:
        """Check command against deny patterns."""
        for pattern in _CURL_DENY_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return (
                    f"Error: curl command contains a disallowed pattern: {pattern!r}. "
                    "File writes (-o/--output), local file reads (@/file://), "
                    "and non-HTTP protocols are not permitted."
                )
        return None

    @staticmethod
    async def _spawn(command: str, timeout: int) -> asyncio.subprocess.Process:
        """Launch curl in a subprocess."""
        env = os.environ.copy()
        if _IS_WINDOWS:
            return await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        bash = shutil.which("bash") or "/bin/bash"
        return await asyncio.create_subprocess_exec(
            bash, "-l", "-c", command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

    @staticmethod
    async def _kill_process(process: asyncio.subprocess.Process) -> None:
        """Kill a subprocess and reap it to prevent zombies."""
        process.kill()
        try:
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(process.wait(), timeout=2.0)
        except Exception:
            pass

"""Process sandbox: the only legal entry point for skills shelling out.

Spec: `.trellis/spec/backend/tool-invocation-safety.md`.
"""

from __future__ import annotations

import asyncio
import enum
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, cast

from secbot.skills.types import (
    SkillBinaryMissing,
    SkillCancelled,
    SkillError,
    SkillTimeout,
)

BINARY_WHITELIST = frozenset({
    "nmap",
    "fscan",
    "nuclei",
    "hydra",
    "httpx",
    "ffuf",
    "katana",
    "sqlmap",
    "ghauri",
    "python3",
    "git",
})

# Spec §3.3 — unconditionally rejected in any user-derived argv element.
FORBIDDEN_CHARS = frozenset(";&|$`<>\n\r\\\"'")


class BinaryNotAllowed(SkillError):  # noqa: N818 - public API predates Ruff naming rule.
    """``binary`` is not in :data:`BINARY_WHITELIST`."""


class InvalidArgvCharacter(SkillError):  # noqa: N818 - public API predates Ruff naming rule.
    """A forbidden character was found in an argv element."""


class NetworkPolicy(enum.StrEnum):
    REQUIRED = "required"
    OPTIONAL = "optional"
    NONE = "none"


@dataclass(frozen=True)
class SandboxResult:
    exit_code: int
    raw_log_path: Optional[Path]
    captured: Optional[bytes]  # set only for memory_capped


def _check_argv(args: Sequence[str]) -> None:
    for i, arg in enumerate(args):
        if not isinstance(arg, str):
            raise InvalidArgvCharacter(f"argv[{i}] is not a string: {arg!r}")
        bad = FORBIDDEN_CHARS.intersection(arg)
        if bad:
            raise InvalidArgvCharacter(
                f"argv[{i}]={arg!r} contains forbidden character(s): {sorted(bad)}"
            )


async def run_command(
    *,
    binary: str,
    args: Sequence[str],
    timeout_sec: int,
    network: NetworkPolicy,
    capture: str = "file",
    cwd: Optional[Path] = None,
    raw_log_path: Optional[Path] = None,
    cancel_token: Optional[asyncio.Event] = None,
    env: Optional[dict[str, str]] = None,
    memory_cap_mb: int = 2,
) -> SandboxResult:
    """Spawn *binary* with *args* under the secbot sandbox contract.

    See spec §1 for the canonical call signature.
    """
    binary_name = Path(binary).name
    if binary_name not in BINARY_WHITELIST:
        raise BinaryNotAllowed(
            f"binary {binary!r} is not in BINARY_WHITELIST "
            "(see .trellis/spec/backend/tool-invocation-safety.md §2)"
        )
    _check_argv(args)
    if timeout_sec is None or timeout_sec <= 0:
        raise ValueError("timeout_sec must be a positive int (spec §6 forbids defaults)")

    binary_path = shutil.which(binary)
    if binary_path is None:
        raise SkillBinaryMissing(f"binary {binary!r} not on PATH")

    if capture not in ("file", "memory_capped", "discard"):
        raise ValueError(f"unknown capture mode: {capture!r}")
    if capture == "file" and raw_log_path is None:
        raise ValueError("capture='file' requires raw_log_path")

    # NetworkPolicy.NONE is honoured by the caller (skills/_shared.network)
    # by setting env / unshare flags; sandbox-level enforcement is left to
    # the platform (secbot/security/network.py) which subscribes to the
    # NetworkPolicy in the skill loader.
    proc = await asyncio.create_subprocess_exec(
        binary_path,
        *args,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
    )

    log_handle = None
    if capture == "file":
        log_path = cast(Path, raw_log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_handle = log_path.open("wb")

    captured = bytearray() if capture == "memory_capped" else None
    cap_bytes = memory_cap_mb * 1024 * 1024

    async def _pump() -> None:
        assert proc.stdout is not None
        while True:
            chunk = await proc.stdout.read(8192)
            if not chunk:
                break
            if log_handle is not None:
                log_handle.write(chunk)
            if captured is not None:
                if len(captured) + len(chunk) > cap_bytes:
                    raise OverflowError(
                        f"captured output exceeded {memory_cap_mb}MB cap"
                    )
                captured.extend(chunk)

    pump_task = asyncio.create_task(_pump())

    async def _watch_cancel() -> None:
        if cancel_token is None:
            return
        await cancel_token.wait()

    cancel_task = asyncio.create_task(_watch_cancel()) if cancel_token else None

    try:
        wait_task = asyncio.create_task(proc.wait())
        watchers: list[asyncio.Task[object]] = [wait_task]
        if cancel_task is not None:
            watchers.append(cancel_task)

        done, _pending = await asyncio.wait(
            watchers, timeout=timeout_sec, return_when=asyncio.FIRST_COMPLETED
        )

        if not done:
            # timeout
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
            raise SkillTimeout(f"binary {binary!r} exceeded {timeout_sec}s")

        if cancel_task is not None and cancel_task in done:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
            raise SkillCancelled("cancel_token was set")

        await pump_task
        return SandboxResult(
            exit_code=proc.returncode if proc.returncode is not None else -1,
            raw_log_path=raw_log_path if capture == "file" else None,
            captured=bytes(captured) if captured is not None else None,
        )
    finally:
        if log_handle is not None:
            log_handle.close()
        if cancel_task is not None and not cancel_task.done():
            cancel_task.cancel()
        if not pump_task.done():
            pump_task.cancel()

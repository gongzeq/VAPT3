"""Shared types for secbot skills.

Spec: `.trellis/spec/backend/skill-contract.md` §3.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

# ---------------------------------------------------------------------------
# Exceptions surfaced to the loop
# ---------------------------------------------------------------------------


class SkillError(Exception):
    """Base class for runtime skill failures the loop should reify as tool errors."""


class SkillBinaryMissing(SkillError):  # noqa: N818 - public API uses this name.
    """Required external binary not found on PATH at invocation time."""


class SkillTimeout(SkillError):  # noqa: N818 - public API uses this name.
    """Subprocess exceeded ``timeout_sec``."""


class SkillCancelled(SkillError):  # noqa: N818 - public API uses this name.
    """``ctx.cancel_token`` was set before the skill finished."""


class InvalidSkillArg(SkillError):  # noqa: N818 - public API uses this name.
    """User-influenced argv element failed the skill's allow-regex."""


# ---------------------------------------------------------------------------
# SkillContext / SkillResult
# ---------------------------------------------------------------------------


@dataclass
class SkillResult:
    """Return value contract for ``handler.run``.

    Spec §3 / §5.
    """

    summary: dict[str, Any]
    raw_log_path: Optional[str] = None
    findings: list[dict[str, Any]] = field(default_factory=list)
    cmdb_writes: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SkillContext:
    """Runtime context handed to ``handler.run``.

    Spec §3.1. Fields kept minimal so unit tests can construct one without
    standing up the full agent loop.
    """

    scan_id: str
    scan_dir: Path
    cancel_token: asyncio.Event = field(default_factory=asyncio.Event)
    confirm: Callable[[str], Awaitable[bool]] = field(
        default_factory=lambda: _default_no_confirm
    )
    progress: Optional[Callable[[float, str], Awaitable[None]]] = None

    def __post_init__(self) -> None:
        self.scan_dir = self.scan_dir.expanduser().resolve()

    async def write_progress(self, pct: float, message: str) -> None:
        if self.progress is not None:
            await self.progress(pct, message)

    @property
    def raw_log_dir(self) -> Path:
        d = self.scan_dir / "raw"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def raw_log_path(self, name: str) -> Path:
        """Return the canonical raw-log path for a skill-local log filename."""
        log_name = Path(name)
        if log_name.is_absolute() or log_name.name != name or "\\" in name:
            raise ValueError(f"raw log name must be a filename, got {name!r}")
        return self.raw_log_dir / name


async def _default_no_confirm(_prompt: str) -> bool:
    """Default ``confirm`` rejects everything to fail safe in unit tests."""
    return False

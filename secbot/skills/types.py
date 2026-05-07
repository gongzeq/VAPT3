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


class SkillBinaryMissing(SkillError):
    """Required external binary not found on PATH at invocation time."""


class SkillTimeout(SkillError):
    """Subprocess exceeded ``timeout_sec``."""


class SkillCancelled(SkillError):
    """``ctx.cancel_token`` was set before the skill finished."""


class InvalidSkillArg(SkillError):
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

    async def write_progress(self, pct: float, message: str) -> None:
        if self.progress is not None:
            await self.progress(pct, message)

    @property
    def raw_log_dir(self) -> Path:
        d = self.scan_dir / "raw"
        d.mkdir(parents=True, exist_ok=True)
        return d


async def _default_no_confirm(_prompt: str) -> bool:
    """Default ``confirm`` rejects everything to fail safe in unit tests."""
    return False

"""High-risk skill confirmation gate.

Spec: `.trellis/spec/backend/high-risk-confirmation.md`.

Wraps the call to a skill's ``handler.run`` with a blocking user-confirmation
step whenever the skill's ``risk_level`` is ``critical``. Non-critical skills
pass through unchanged.

The gate is surface-agnostic: it composes a structured payload and delegates
to ``ctx.confirm(prompt)``. The actual dialog rendering is the Surface's
problem (WebUI modal / CLI prompt).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping, Optional

from secbot.skills.metadata import SkillMetadata
from secbot.skills.types import SkillContext, SkillResult

_LOG = logging.getLogger(__name__)

DEFAULT_CONFIRM_TIMEOUT_SEC = 120


@dataclass
class AuditLogger:
    """Append-only audit sink. Default implementation stores in-memory.

    Production wiring points it at the ``audit_log`` CMDB table; unit tests
    use the default list-backed implementation.
    """

    entries: list[dict[str, Any]] = field(default_factory=list)

    def emit(
        self,
        scan_id: str,
        skill: str,
        action: str,
        payload: Optional[Mapping[str, Any]] = None,
    ) -> None:
        if action not in {
            "confirm_request",
            "confirm_approve",
            "confirm_deny",
            "confirm_timeout",
        }:
            raise ValueError(f"unknown audit action: {action!r}")
        self.entries.append(
            {
                "scan_id": scan_id,
                "skill": skill,
                "action": action,
                "payload": dict(payload) if payload else {},
                "ts": time.time(),
            }
        )


def build_confirmation_payload(
    meta: SkillMetadata,
    args: Mapping[str, Any],
    scan_id: str,
    *,
    summary_for_user: Optional[str] = None,
    estimated_duration_sec: Optional[int] = None,
) -> dict[str, Any]:
    """Compose the structured ``high_risk_confirm`` event (spec §2.1)."""
    return {
        "type": "high_risk_confirm",
        "skill": meta.name,
        "display_name": meta.display_name,
        "risk_level": meta.risk_level,
        "summary_for_user": summary_for_user
        or f"Run {meta.display_name} with args: {dict(args)}",
        "args": dict(args),
        "estimated_duration_sec": estimated_duration_sec
        or meta.expected_runtime_sec,
        "destructive_action": True,
        "scan_id": scan_id,
    }


class HighRiskDenied(Exception):
    """Raised internally when the user denies a critical confirmation."""


@dataclass
class HighRiskGate:
    """Stateful gate that audits every confirmation and honours a timeout."""

    audit: AuditLogger = field(default_factory=AuditLogger)
    timeout_sec: int = DEFAULT_CONFIRM_TIMEOUT_SEC
    summary_fn: Optional[
        Callable[[SkillMetadata, Mapping[str, Any]], str]
    ] = None

    async def guard(
        self,
        meta: SkillMetadata,
        args: Mapping[str, Any],
        ctx: SkillContext,
        run: Callable[[Mapping[str, Any], SkillContext], Awaitable[SkillResult]],
    ) -> SkillResult:
        """Maybe prompt the user, then call ``run`` (or short-circuit)."""
        if not meta.is_critical():
            return await run(args, ctx)

        summary = (
            self.summary_fn(meta, args) if self.summary_fn else None
        )
        payload = build_confirmation_payload(
            meta, args, ctx.scan_id, summary_for_user=summary
        )
        self.audit.emit(ctx.scan_id, meta.name, "confirm_request", payload)

        try:
            approved = await asyncio.wait_for(
                ctx.confirm(payload), timeout=self.timeout_sec
            )
        except asyncio.TimeoutError:
            self.audit.emit(ctx.scan_id, meta.name, "confirm_timeout")
            _LOG.warning("high-risk confirm timed out: %s", meta.name)
            return SkillResult(
                summary={"user_denied": True, "reason": "confirm_timeout"},
            )

        if not approved:
            self.audit.emit(ctx.scan_id, meta.name, "confirm_deny")
            return SkillResult(summary={"user_denied": True, "reason": "denied"})

        self.audit.emit(ctx.scan_id, meta.name, "confirm_approve")
        return await run(args, ctx)

"""Wall-clock and tool-call budget tracking for Pi orchestration.

Spec: `.trellis/spec/backend/budget-enforcer.md`.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from threading import RLock
from typing import Any, Literal

BudgetStatus = Literal["HEALTHY", "LOW", "EXCEEDED"]


class BudgetExhausted(RuntimeError):  # noqa: N818 - spec name
    """Raised when a worker share would over-commit the master budget."""


class BudgetExtendDisabled(RuntimeError):  # noqa: N818 - spec name
    """Raised when budget extension is disabled by configuration."""


@dataclass(frozen=True, slots=True)
class BudgetView:
    """Read-only budget view exposed to prompts and policy checks."""

    wall_clock_used_sec: float
    wall_clock_max_sec: float
    tool_calls_used: int
    tool_calls_max: int
    low_threshold_pct: float = 90.0
    enabled: bool = True
    worker_id: str | None = None

    @property
    def wall_clock_remaining_sec(self) -> float:
        return max(0.0, self.wall_clock_max_sec - self.wall_clock_used_sec)

    @property
    def tool_calls_remaining(self) -> int:
        return max(0, self.tool_calls_max - self.tool_calls_used)

    @property
    def wall_clock_pct(self) -> float:
        if self.wall_clock_max_sec <= 0:
            return 0.0 if not self.enabled else 100.0
        return (self.wall_clock_used_sec / self.wall_clock_max_sec) * 100.0

    @property
    def tool_call_pct(self) -> float:
        if self.tool_calls_max <= 0:
            return 0.0 if not self.enabled else 100.0
        return (self.tool_calls_used / self.tool_calls_max) * 100.0

    @property
    def status(self) -> BudgetStatus:
        if not self.enabled:
            return "HEALTHY"
        peak = max(self.wall_clock_pct, self.tool_call_pct)
        if peak >= 100.0:
            return "EXCEEDED"
        if peak >= self.low_threshold_pct:
            return "LOW"
        return "HEALTHY"

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "worker_id": self.worker_id,
            "status": self.status,
            "wall_clock_used_sec": self.wall_clock_used_sec,
            "wall_clock_max_sec": self.wall_clock_max_sec,
            "wall_clock_remaining_sec": self.wall_clock_remaining_sec,
            "wall_clock_pct": self.wall_clock_pct,
            "tool_calls_used": self.tool_calls_used,
            "tool_calls_max": self.tool_calls_max,
            "tool_calls_remaining": self.tool_calls_remaining,
            "tool_call_pct": self.tool_call_pct,
        }


@dataclass(slots=True)
class BudgetShare:
    """Sub-budget granted to a worker at spawn time."""

    worker_id: str
    max_wall_clock_sec: float
    max_tool_calls: int
    wall_clock_start: float
    tool_calls_used: int = 0

    def view(
        self,
        *,
        now: float,
        low_threshold_pct: float,
        enabled: bool,
    ) -> BudgetView:
        return BudgetView(
            wall_clock_used_sec=max(0.0, now - self.wall_clock_start),
            wall_clock_max_sec=self.max_wall_clock_sec,
            tool_calls_used=self.tool_calls_used,
            tool_calls_max=self.max_tool_calls,
            low_threshold_pct=low_threshold_pct,
            enabled=enabled,
            worker_id=self.worker_id,
        )


class BudgetTracker:
    """In-memory master budget plus reserved worker shares."""

    def __init__(
        self,
        chat_id: str,
        *,
        wall_clock_max_sec: float = 900.0,
        tool_calls_max: int = 60,
        low_threshold_pct: float = 90.0,
        enabled: bool = True,
        allow_extend: bool = True,
        event_sink: Callable[[str, Mapping[str, Any]], None] | None = None,
        time_fn: Callable[[], float] | None = None,
    ) -> None:
        self.chat_id = chat_id
        self.wall_clock_max_sec = float(wall_clock_max_sec)
        self.tool_calls_max = int(tool_calls_max)
        self.low_threshold_pct = float(low_threshold_pct)
        self.enabled = bool(enabled)
        self.allow_extend = bool(allow_extend)
        self._event_sink = event_sink
        self._time_fn = time_fn or time.monotonic
        self._lock = RLock()
        self._wall_clock_start = self._time_fn()
        self._tool_calls_used = 0
        self._worker_shares: dict[str, BudgetShare] = {}
        self._emit("budget_started", self.status().as_dict())

    def start(self) -> None:
        """Reset clocks, counters, and open worker shares."""
        with self._lock:
            self._wall_clock_start = self._time_fn()
            self._tool_calls_used = 0
            self._worker_shares.clear()
            view = self._view_locked()
        self._emit("budget_started", view.as_dict())

    def on_tool_call(self, worker_id: str | None = None) -> None:
        """Increment master and optional worker counters after execution."""
        if not self.enabled:
            return
        with self._lock:
            self._tool_calls_used += 1
            if worker_id and worker_id in self._worker_shares:
                self._worker_shares[worker_id].tool_calls_used += 1
            view = self._view_locked(worker_id=worker_id)
        self._emit("budget_tool_call", view.as_dict())

    def status(self, worker_id: str | None = None) -> BudgetView:
        with self._lock:
            return self._view_locked(worker_id=worker_id)

    def is_exceeded(self, worker_id: str | None = None) -> bool:
        return self.status(worker_id=worker_id).status == "EXCEEDED"

    def grant_share(
        self,
        worker_id: str,
        max_wall_clock_sec: float,
        max_tool_calls: int,
    ) -> BudgetShare:
        """Reserve a worker sub-budget without over-committing the master."""
        worker_id = str(worker_id).strip()
        if not worker_id:
            raise BudgetExhausted("worker_id is required")
        max_wall_clock_sec = float(max_wall_clock_sec)
        max_tool_calls = int(max_tool_calls)
        if max_wall_clock_sec < 0 or max_tool_calls < 0:
            raise BudgetExhausted("budget share values must be non-negative")

        with self._lock:
            if worker_id in self._worker_shares:
                raise BudgetExhausted(f"worker {worker_id} already has a budget share")
            master = self._view_locked()
            reserved_calls = sum(share.max_tool_calls for share in self._worker_shares.values())
            reserved_wall = sum(
                share.max_wall_clock_sec for share in self._worker_shares.values()
            )
            if self.enabled and reserved_calls + max_tool_calls > master.tool_calls_remaining:
                raise BudgetExhausted(
                    "worker share would exceed remaining master tool-call budget"
                )
            if self.enabled and reserved_wall + max_wall_clock_sec > master.wall_clock_remaining_sec:
                raise BudgetExhausted(
                    "worker share would exceed remaining master wall-clock budget"
                )
            share = BudgetShare(
                worker_id=worker_id,
                max_wall_clock_sec=max_wall_clock_sec,
                max_tool_calls=max_tool_calls,
                wall_clock_start=self._time_fn(),
            )
            self._worker_shares[worker_id] = share
        self._emit(
            "budget_share_granted",
            {
                "chat_id": self.chat_id,
                "worker_id": worker_id,
                "max_wall_clock_sec": max_wall_clock_sec,
                "max_tool_calls": max_tool_calls,
            },
        )
        return share

    def reclaim_share(self, worker_id: str) -> None:
        """Release an open worker share."""
        with self._lock:
            share = self._worker_shares.pop(worker_id, None)
        if share is not None:
            self._emit(
                "budget_share_reclaimed",
                {
                    "chat_id": self.chat_id,
                    "worker_id": worker_id,
                    "unused_tool_calls": max(0, share.max_tool_calls - share.tool_calls_used),
                },
            )

    def extend(
        self,
        *,
        extra_wall_clock_sec: float = 0.0,
        extra_tool_calls: int = 0,
    ) -> None:
        """Extend the master budget after a user-driven decision."""
        if not self.allow_extend:
            raise BudgetExtendDisabled("budget extension is disabled")
        with self._lock:
            self.wall_clock_max_sec += max(0.0, float(extra_wall_clock_sec))
            self.tool_calls_max += max(0, int(extra_tool_calls))
            view = self._view_locked()
        self._emit("budget_extended", view.as_dict())

    def _view_locked(self, worker_id: str | None = None) -> BudgetView:
        now = self._time_fn()
        if worker_id and worker_id in self._worker_shares:
            return self._worker_shares[worker_id].view(
                now=now,
                low_threshold_pct=self.low_threshold_pct,
                enabled=self.enabled,
            )
        return BudgetView(
            wall_clock_used_sec=max(0.0, now - self._wall_clock_start),
            wall_clock_max_sec=self.wall_clock_max_sec,
            tool_calls_used=self._tool_calls_used,
            tool_calls_max=self.tool_calls_max,
            low_threshold_pct=self.low_threshold_pct,
            enabled=self.enabled,
        )

    def _emit(self, type_: str, payload: Mapping[str, Any]) -> None:
        if self._event_sink is None:
            return
        try:
            self._event_sink(type_, payload)
        except Exception:
            return


def format_duration(seconds: float) -> str:
    seconds_i = max(0, int(round(seconds)))
    minutes, secs = divmod(seconds_i, 60)
    return f"{minutes}m{secs:02d}s"


def render_budget_section(view: BudgetView) -> str:
    """Render the dynamic `# Budget` prompt section."""
    wall_pct = int(round(view.wall_clock_pct))
    calls_pct = int(round(view.tool_call_pct))
    return "\n".join(
        [
            "# Budget",
            (
                "wall_clock:        "
                f"used {format_duration(view.wall_clock_used_sec)} / "
                f"{format_duration(view.wall_clock_max_sec)} "
                f"({wall_pct}% used, {format_duration(view.wall_clock_remaining_sec)} left)"
            ),
            (
                "tool_calls:        "
                f"used {view.tool_calls_used} / {view.tool_calls_max} "
                f"({calls_pct}% used, {view.tool_calls_remaining} left)"
            ),
            f"status:            {view.status}",
        ]
    )


def inject_exceeded_message(view: BudgetView, *, current_phase: str = "Intake") -> str:
    """Build the BUDGET_EXCEEDED system message for the next LLM turn."""
    return "\n".join(
        [
            "[BUDGET_EXCEEDED]",
            (
                f"wall_clock: {format_duration(view.wall_clock_used_sec)} / "
                f"{format_duration(view.wall_clock_max_sec)} "
                f"({view.wall_clock_pct:.1f}%)"
            ),
            (
                f"tool_calls: {view.tool_calls_used} / {view.tool_calls_max} "
                f"({view.tool_call_pct:.1f}%)"
            ),
            "",
            "You MUST do the following BEFORE any further tool call:",
            (
                '1. Call `write_blackboard(kind="summary", '
                'payload={"kind":"findings_summary","items":[...]})`.'
            ),
            (
                '2. Call `write_blackboard(kind="summary", '
                'payload={"kind":"blockers_summary","items":[...]})`.'
            ),
            (
                '3. Call `write_blackboard(kind="summary", '
                'payload={"kind":"next_steps","items":[...]})`.'
            ),
            (
                '4. Call `write_blackboard(kind="phase_transition", payload={"from":"'
                f"{current_phase}"
                '","to":"Checkpoint","reason":"budget_exhausted"})`.'
            ),
            "5. Use `message(content=...)` to inform the user.",
            "",
            "The PolicyEngine will deny every other tool call until checkpoint work is complete.",
        ]
    )

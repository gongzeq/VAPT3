"""Abstract step executor + shared timing / error wrapper.

The concrete executors only need to implement :meth:`StepExecutor._run`
and return the raw ``output`` (anything JSON-serialisable) or raise
:class:`ExecutorError`. The base class records ``started_at_ms`` /
``finished_at_ms`` / ``duration_ms`` and builds the final
:class:`StepResult`.

Contract:

* ``output`` must be JSON-serialisable so it can round-trip through
  ``runs.jsonl`` and be referenced from templates via
  ``${steps.<id>.result.<path>}``.
* ``ExecutorError`` (or subclasses) is caught and mapped to
  ``status="error"`` with ``error=str(exc)``. Any other exception is
  also caught and reported with ``workflow.executor.unexpected: <msg>``
  — executors MUST NOT propagate unhandled exceptions to the runner.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from secbot.workflow.types import StepResult, WorkflowStep


class ExecutorError(Exception):
    """User-facing step failure. Serialised verbatim into StepResult.error."""


@dataclass
class StepContext:
    """Non-argument state an executor may need to read.

    ``inputs`` — the workflow-level inputs (resolved against defaults).
    ``steps`` — per-step-id results accumulated so far. Used by the
    runner for template interpolation; executors should not normally
    need to inspect this, but the field is exposed for advanced cases
    (e.g., an ``agent`` executor peeking at upstream structured output).
    ``env`` — snapshot of environment variables at run-start (copy, not
    live reference). Matches api-spec ``${env.*}``.
    ``run_id`` — the enclosing :class:`WorkflowRun` id, useful for
    logging / progress emission.
    """

    inputs: dict[str, Any] = field(default_factory=dict)
    steps: dict[str, Any] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)
    run_id: str = ""


def _now_ms() -> int:
    return int(time.time() * 1000)


class StepExecutor(ABC):
    """Abstract executor. Subclasses implement :meth:`_run`."""

    kind: str = "unknown"

    async def execute(
        self,
        step: WorkflowStep,
        args: dict[str, Any],
        ctx: StepContext,
    ) -> StepResult:
        """Run the step and produce a :class:`StepResult` with timing.

        Never raises — any exception is translated into a StepResult with
        ``status="error"``. The runner relies on this invariant to keep
        the on_error / retry loop clean.
        """
        started = _now_ms()
        try:
            output = await self._run(step, args, ctx)
            finished = _now_ms()
            return StepResult(
                status="ok",
                started_at_ms=started,
                finished_at_ms=finished,
                duration_ms=finished - started,
                output=output,
            )
        except ExecutorError as exc:
            finished = _now_ms()
            return StepResult(
                status="error",
                started_at_ms=started,
                finished_at_ms=finished,
                duration_ms=finished - started,
                error=str(exc),
            )
        except Exception as exc:  # pragma: no cover — defensive last-resort
            finished = _now_ms()
            return StepResult(
                status="error",
                started_at_ms=started,
                finished_at_ms=finished,
                duration_ms=finished - started,
                error=f"workflow.executor.unexpected: {exc}",
            )

    @abstractmethod
    async def _run(
        self,
        step: WorkflowStep,
        args: dict[str, Any],
        ctx: StepContext,
    ) -> Any:
        """Execute the step; return the ``output`` payload. Raise
        :class:`ExecutorError` for user-visible failures.
        """

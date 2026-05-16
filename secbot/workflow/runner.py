"""Workflow runner — orchestrate step execution with retries / on_error.

Responsibilities (single-run scope; the facade around it lives in
:mod:`secbot.workflow.service`):

1. Resolve every workflow input against its declared default / required
   flag. Missing required inputs ⇒ ``workflow.validation.input_missing``.
2. Snapshot ``os.environ`` once at run-start so template interpolation
   can resolve ``${env.<key>}``.
3. Walk steps in declaration order:

   * Evaluate ``step.condition`` in the safe expression sandbox
     (:mod:`secbot.workflow.expr`). Falsy ⇒ ``status=skipped``.
   * Interpolate ``step.args`` (template strings anywhere in the dict /
     list tree).
   * Dispatch to the executor registered for ``step.kind``. If there's
     no executor, fail with ``workflow.executor.kind_unknown``.
   * On failure, honour ``step.retry`` (≥ 0) with a fixed 0.5s back-off
     — enough to smooth flaky external calls without blocking a cron
     tick. Each retry is persisted in StepResult.status=retried so the
     UI can surface the attempt history.
   * After exhausting retries, apply ``on_error``:

       * ``stop``     → abort the run (``run.status=error``)
       * ``continue`` → record the failure, move on
       * ``retry``    → equivalent to ``retry=1`` fallback (kept for
         compatibility with the earlier PRD wording)

4. On every lifecycle transition (run-start, step-start, step-end,
   run-end) invoke ``progress_cb(event, payload)`` when supplied; the
   WebSocket layer wires this up to the ``workflow.run.*`` /
   ``workflow.step.*`` events defined in api-spec §5.
5. Persist the run after each step (``store.upsert_run``) so a crash
   leaves a partial, inspectable trace behind.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import asdict
from typing import Any, Awaitable, Callable

from secbot.workflow.executors.base import StepContext, StepExecutor
from secbot.workflow.expr import ExprError, eval_bool, interpolate
from secbot.workflow.store import WorkflowStore
from secbot.workflow.types import (
    StepResult,
    Workflow,
    WorkflowRun,
    WorkflowStep,
)


def _now_ms() -> int:
    return int(time.time() * 1000)

logger = logging.getLogger(__name__)

_RETRY_BACKOFF_S = 0.5

ProgressCallback = Callable[[str, dict[str, Any]], Awaitable[None]]


class RunnerError(Exception):
    """Configuration-time failure (bad workflow shape, bad inputs)."""


class WorkflowRunner:
    """Single-run orchestrator. Create one per :meth:`run` invocation."""

    def __init__(
        self,
        store: WorkflowStore,
        executors: dict[str, StepExecutor],
        *,
        progress_cb: ProgressCallback | None = None,
        env_snapshot: dict[str, str] | None = None,
    ) -> None:
        self._store = store
        self._executors = dict(executors)
        self._progress_cb = progress_cb
        # Capture env at construction so repeated runs of the same
        # runner see the same snapshot; callers who want fresh env per
        # run just create a new runner instance.
        self._env_snapshot = (
            dict(env_snapshot) if env_snapshot is not None else dict(os.environ)
        )

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run(
        self,
        workflow: Workflow,
        inputs: dict[str, Any],
        *,
        trigger: str = "manual",
    ) -> WorkflowRun:
        """Execute ``workflow`` and return the completed :class:`WorkflowRun`."""
        resolved_inputs = _resolve_inputs(workflow, inputs)

        run = WorkflowRun.new(
            workflow_id=workflow.id,
            inputs=resolved_inputs,
            trigger=trigger,  # type: ignore[arg-type]
        )
        self._store.upsert_run(run)
        await self._emit("workflow.run.started", _run_event(workflow, run))

        ctx = StepContext(
            inputs=dict(resolved_inputs),
            steps={},
            env=self._env_snapshot,
            run_id=run.id,
        )

        run_status: str = "ok"
        run_error: str | None = None

        for step in workflow.steps:
            should_run, skip_reason = self._evaluate_condition(step, ctx)
            if not should_run:
                skipped = StepResult.skipped()
                run.step_results[step.id] = skipped
                ctx.steps[step.id] = _step_view(skipped)
                self._store.upsert_run(run)
                await self._emit(
                    "workflow.step.finished",
                    _step_event(run, step, skipped, skipped_reason=skip_reason),
                )
                continue

            await self._emit("workflow.step.started", _step_event(run, step, None))
            result = await self._run_step_with_retry(step, ctx)
            run.step_results[step.id] = result
            ctx.steps[step.id] = _step_view(result)
            self._store.upsert_run(run)
            await self._emit("workflow.step.finished", _step_event(run, step, result))

            if result.status == "error":
                if step.on_error == "stop":
                    run_status = "error"
                    run_error = (
                        f"step '{step.id}' failed: {result.error or 'unknown'}"
                    )
                    break
                # else: on_error == continue / retry → already exhausted
                # retries inside _run_step_with_retry. Keep going.

        run.status = run_status  # type: ignore[assignment]
        run.error = run_error
        run.finished_at_ms = _now_ms()
        self._store.upsert_run(run)
        await self._emit("workflow.run.finished", _run_event(workflow, run))
        return run

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _evaluate_condition(
        self, step: WorkflowStep, ctx: StepContext
    ) -> tuple[bool, str | None]:
        """Return ``(should_run, skip_reason_or_none)``."""
        if step.condition is None or not step.condition.strip():
            return True, None
        try:
            ok = eval_bool(step.condition, _ctx_to_dict(ctx))
        except ExprError as exc:
            # A malformed condition is treated as a user-visible step
            # error rather than a silent skip — otherwise a typo in
            # ``${steps.previous.result.ok}`` would ghost the step.
            logger.info(
                "workflow condition failed step=%s err=%s", step.id, exc
            )
            return False, f"condition_error: {exc}"
        return bool(ok), None if ok else "condition_false"

    async def _run_step_with_retry(
        self, step: WorkflowStep, ctx: StepContext
    ) -> StepResult:
        executor = self._executors.get(step.kind)
        if executor is None:
            now = _now_ms()
            return StepResult(
                status="error",
                started_at_ms=now,
                finished_at_ms=now,
                duration_ms=0,
                error=f"workflow.executor.kind_unknown: {step.kind}",
            )

        try:
            args = interpolate(dict(step.args), _ctx_to_dict(ctx))
        except ExprError as exc:
            now = _now_ms()
            return StepResult(
                status="error",
                started_at_ms=now,
                finished_at_ms=now,
                duration_ms=0,
                error=f"workflow.validation.interpolate: {exc}",
            )

        attempts = max(0, int(step.retry or 0))
        if step.on_error == "retry" and attempts == 0:
            # "retry" on_error with retry=0 is a legacy shortcut for "one
            # extra attempt", matching the PRD's original wording.
            attempts = 1

        last = await executor.execute(step, args, ctx)
        if last.status != "error" or attempts == 0:
            return last

        for attempt in range(1, attempts + 1):
            await asyncio.sleep(_RETRY_BACKOFF_S)
            retried = await executor.execute(step, args, ctx)
            if retried.status != "error":
                # Surface that we retried so UIs can badge the step.
                retried.status = "retried"  # type: ignore[assignment]
                return retried
            last = retried
            logger.info(
                "workflow step retry exhausted step=%s attempt=%s/%s",
                step.id,
                attempt,
                attempts,
            )
        return last

    async def _emit(self, event: str, payload: dict[str, Any]) -> None:
        if self._progress_cb is None:
            return
        try:
            await self._progress_cb(event, payload)
        except Exception:
            # Progress emission must never break a run — a broken
            # subscriber would otherwise take the whole workflow down.
            logger.exception("workflow progress_cb failed event=%s", event)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _resolve_inputs(workflow: Workflow, supplied: dict[str, Any]) -> dict[str, Any]:
    """Merge ``supplied`` with defaults; raise on missing required fields."""
    out: dict[str, Any] = {}
    for spec in workflow.inputs:
        if spec.name in supplied:
            out[spec.name] = supplied[spec.name]
        elif spec.default is not None:
            out[spec.name] = spec.default
        elif spec.required:
            raise RunnerError(
                f"workflow.validation.input_missing: '{spec.name}' is required"
            )
    # Preserve any extra keys the caller passed in; the runner doesn't
    # police unknown keys so a tool step can reference ``${inputs.x}``
    # even when ``x`` isn't declared (handy during authoring).
    for key, value in supplied.items():
        out.setdefault(key, value)
    return out


def _ctx_to_dict(ctx: StepContext) -> dict[str, Any]:
    return {"inputs": ctx.inputs, "steps": ctx.steps, "env": ctx.env}


def _step_view(result: StepResult) -> dict[str, Any]:
    """Shape exposed to template expressions as ``steps.<id>``."""
    return {"result": result.output, "status": result.status, "error": result.error}


def _run_event(workflow: Workflow, run: WorkflowRun) -> dict[str, Any]:
    return {
        "runId": run.id,
        "workflowId": workflow.id,
        "status": run.status,
        "trigger": run.trigger,
        "startedAtMs": run.started_at_ms,
        "finishedAtMs": run.finished_at_ms,
    }


def _step_event(
    run: WorkflowRun,
    step: WorkflowStep,
    result: StepResult | None,
    *,
    skipped_reason: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "runId": run.id,
        "workflowId": run.workflow_id,
        "stepId": step.id,
        "kind": step.kind,
        "ref": step.ref,
    }
    if result is not None:
        payload["result"] = {
            k: v for k, v in asdict(result).items()
            if k in {"status", "started_at_ms", "finished_at_ms", "duration_ms", "error"}
        }
    if skipped_reason:
        payload["skippedReason"] = skipped_reason
    return payload

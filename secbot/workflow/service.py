"""WorkflowService — façade over store + runner + registries.

Wiring diagram::

    ┌────────┐   save/list/delete   ┌─────────────────┐
    │REST    │ ────────────────────▶│ WorkflowService │
    │handlers│ ◀──────────────────── │  (this module)  │
    └────────┘   workflows / runs   └─────────────────┘
                                            │
                 ┌──────────────────────────┼──────────────────────────┐
                 ▼                          ▼                          ▼
           WorkflowStore             WorkflowRunner               Executors
         (JSON + filelock)     (condition / retry / env)   (tool / script / agent / llm)

The service also owns **cron synchronisation**: when a workflow declares
a ``schedule_ref``, the service adds / updates a matching ``CronJob``
with payload ``message = "__workflow__:<wf_id>:<inputs_json>"`` so the
scheduler callback (installed in ``secbot/cli/commands.py::on_cron_job``)
can dispatch back to :meth:`run`. Cron sync is best-effort: if the
``cron_service`` argument is ``None`` the schedule-related APIs return
a structured error instead of blowing up.

All methods are ``async`` for symmetry with the runner and to future-
proof against an RDBMS-backed store; the current JSON store is
synchronous under the hood.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Awaitable, Callable

from secbot.workflow.executors import build_default_executors
from secbot.workflow.executors.base import StepExecutor
from secbot.workflow.runner import WorkflowRunner
from secbot.workflow.store import WorkflowStore
from secbot.workflow.types import (
    Workflow,
    WorkflowInput,
    WorkflowRun,
    WorkflowStep,
)

logger = logging.getLogger(__name__)

# suggested_action values that map to "alert" status (mirror
# secbot.api.log_analysis_dashboard._ACTION_TO_STATUS).
_ALERT_ACTIONS = frozenset({"告警", "紧急处理"})


def _publish_log_alert_if_needed(run: WorkflowRun) -> None:
    """Inspect a completed log-analysis run and publish a notification.

    Called after ``_execute_steps`` finishes.  Reads the final step's
    parsed output (step3) to decide whether the result qualifies as an
    alert.  Best-effort: any failure is logged and swallowed so the
    workflow run itself is never affected.
    """
    try:
        # Find the last step result (step3) which contains the persisted
        # analysis output including ``suggested_action`` and ``last_id``.
        step3_result = run.step_results.get("step3")
        if step3_result is None or step3_result.status != "success":
            return
        output = step3_result.output
        if not isinstance(output, dict):
            return
        parsed = output.get("parsed")
        if not isinstance(parsed, dict):
            return

        action = str(parsed.get("suggested_action") or "")
        if action not in _ALERT_ACTIONS:
            return

        last_id = int(parsed.get("last_id") or 0)
        file_name = str(parsed.get("file_name") or "")
        anomaly_count = int(parsed.get("anomaly_count") or 0)

        from secbot.channels.notifications import get_notification_queue

        q = get_notification_queue()
        q.publish(
            type="log_alert",
            title=f"日志安全告警: {file_name}",
            body=(
                f"检测到 {anomaly_count} 条异常，建议操作：{action}"
            ),
            link=f"/dashboard/log-analysis?focus={last_id}" if last_id else "/dashboard/log-analysis",
            ref_type="log_analysis",
            ref_id=last_id if last_id else None,
        )
    except Exception:
        logger.debug("log-alert notification publish failed", exc_info=True)


ProgressCallback = Callable[[str, dict[str, Any]], Awaitable[None]]

_WORKFLOW_MSG_PREFIX = "__workflow__:"


class WorkflowServiceError(Exception):
    """User-visible façade error (validation / missing dependency)."""


class WorkflowService:
    """Thin orchestrator the REST / CLI layers talk to."""

    def __init__(
        self,
        *,
        store_root: Path,
        tool_registry: Any,
        agent_registry: Any = None,
        llm_provider: Any = None,
        provider_loader: Callable[[], Any] | None = None,
        cron_service: Any = None,
        progress_cb: ProgressCallback | None = None,
        executors: dict[str, StepExecutor] | None = None,
    ) -> None:
        self._store = WorkflowStore(store_root)
        self._executors = executors or build_default_executors(
            tool_registry=tool_registry,
            agent_registry=agent_registry,
            llm_provider=llm_provider,
            provider_loader=provider_loader,
        )
        self._cron = cron_service
        self._progress_cb = progress_cb
        # Per-workflow concurrency locks.  Each wf_id gets its own Lock so
        # only one run of the *same* workflow can execute at a time; runs of
        # *different* workflows are not blocked.  The defaultdict lazily
        # creates a Lock the first time a wf_id is seen.
        self._wf_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        # Active runners keyed by run_id so cancel() can reach them.
        self._active_runners: dict[str, WorkflowRunner] = {}

    # ------------------------------------------------------------------
    # Workflow CRUD
    # ------------------------------------------------------------------

    async def list_workflows(self) -> list[Workflow]:
        return self._store.list_workflows()

    async def get_workflow(self, wf_id: str) -> Workflow | None:
        return self._store.get_workflow(wf_id)

    async def save_workflow(self, wf: Workflow) -> Workflow:
        """Insert or replace ``wf``. Does NOT touch cron."""
        _validate_workflow(wf)
        return self._store.save_workflow(wf)

    async def delete_workflow(self, wf_id: str) -> bool:
        """Delete the workflow and detach any cron binding."""
        wf = self._store.get_workflow(wf_id)
        if wf is None:
            return False
        if wf.schedule_ref:
            try:
                await self.detach_schedule(wf_id)
            except WorkflowServiceError:
                logger.exception(
                    "workflow cron detach failed wf=%s ref=%s", wf_id, wf.schedule_ref
                )
        return self._store.delete_workflow(wf_id)

    # ------------------------------------------------------------------
    # Schedule (cron) sync
    # ------------------------------------------------------------------

    async def attach_schedule(
        self,
        wf_id: str,
        schedule: Any,
        *,
        inputs: dict[str, Any] | None = None,
        name: str | None = None,
    ) -> Workflow:
        """Add / refresh a cron job for ``wf_id`` and persist ``schedule_ref``.

        ``schedule`` is a :class:`secbot.cron.types.CronSchedule`. Passing
        it here avoids dragging the cron import into REST handlers.
        """
        wf = self._require_workflow(wf_id)
        if self._cron is None:
            raise WorkflowServiceError(
                "workflow.validation.cron_unavailable: cron service is not wired"
            )
        if wf.schedule_ref:
            await self.detach_schedule(wf_id)

        message = _encode_cron_message(wf_id, inputs or {})
        job = self._cron.add_job(
            name=name or f"workflow:{wf.name}",
            schedule=schedule,
            message=message,
            deliver=False,
        )
        wf.schedule_ref = job.id
        self._store.save_workflow(wf)
        return wf

    async def detach_schedule(self, wf_id: str) -> Workflow:
        """Remove the cron binding (if any) and clear ``schedule_ref``."""
        wf = self._require_workflow(wf_id)
        if wf.schedule_ref and self._cron is not None:
            status = self._cron.remove_job(wf.schedule_ref)
            if status == "protected":
                raise WorkflowServiceError(
                    f"workflow.validation.schedule_protected: "
                    f"cron job {wf.schedule_ref} cannot be removed"
                )
        wf.schedule_ref = None
        self._store.save_workflow(wf)
        return wf

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------

    async def list_runs(
        self, *, workflow_id: str | None = None, limit: int | None = None
    ) -> list[WorkflowRun]:
        return self._store.list_runs(workflow_id=workflow_id, limit=limit)

    async def get_run(self, run_id: str) -> WorkflowRun | None:
        return self._store.get_run(run_id)

    async def run(
        self,
        wf_id: str,
        inputs: dict[str, Any],
        *,
        trigger: str = "manual",
    ) -> WorkflowRun:
        """Execute ``wf_id`` with ``inputs`` and return the completed run.

        Acquires a per-workflow lock so only one run of the same workflow
        can execute at a time.  Concurrent callers block until the lock
        is released.
        """
        wf = self._require_workflow(wf_id)
        lock = self._wf_locks[wf_id]
        async with lock:
            runner = WorkflowRunner(
                self._store, self._executors, progress_cb=self._progress_cb
            )
            run, ctx = runner._prepare_run(wf, inputs, trigger=trigger)
            self._active_runners[run.id] = runner
            try:
                await runner._execute_steps(run, wf, ctx)
            finally:
                self._active_runners.pop(run.id, None)
            # Post-completion: publish notification for log-analysis alerts.
            if wf_id == "log-analysis":
                _publish_log_alert_if_needed(run)
            return run

    async def run_async(
        self,
        wf_id: str,
        inputs: dict[str, Any],
        *,
        trigger: str = "manual",
    ) -> WorkflowRun:
        """Start ``wf_id`` in the background and return the *running* run
        immediately.

        The caller gets back a ``WorkflowRun`` with ``status='running'``
        so the API can respond without waiting for all steps to finish.
        Step execution continues as an ``asyncio.Task`` and acquires a
        per-workflow lock, so concurrent runs of the *same* workflow
        are serialised.
        """
        wf = self._require_workflow(wf_id)
        runner = WorkflowRunner(
            self._store, self._executors, progress_cb=self._progress_cb
        )
        run, ctx = runner._prepare_run(wf, inputs, trigger=trigger)

        async def _bg() -> None:
            lock = self._wf_locks[wf_id]
            async with lock:
                self._active_runners[run.id] = runner
                try:
                    await runner._execute_steps(run, wf, ctx)
                    # Post-completion: publish notification for log-analysis alerts.
                    if wf_id == "log-analysis":
                        _publish_log_alert_if_needed(run)
                except Exception:
                    logger.exception(
                        "Background workflow run %s failed", run.id
                    )
                    run.status = "error"  # type: ignore[assignment]
                    run.error = "unexpected background failure"
                    run.finished_at_ms = int(time.time() * 1000)
                    self._store.upsert_run(run)
                finally:
                    self._active_runners.pop(run.id, None)

        asyncio.create_task(_bg(), name=f"wf-run-{run.id}")
        return run

    async def cancel(self, wf_id: str) -> WorkflowRun | None:
        """Cancel the currently active run for *wf_id*, if any.

        Returns the cancelled :class:`WorkflowRun` or ``None`` if nothing
        was running.
        """
        # Find the active runner whose run belongs to wf_id.
        for run_id, runner in list(self._active_runners.items()):
            run = self._store.get_run(run_id)
            if run is not None and run.workflow_id == wf_id and run.status == "running":
                runner.cancel()
                # The runner loop will set status=cancelled on its next
                # iteration.  Return the current (still running) snapshot;
                # the caller can poll /runs for the final state.
                return run
        return None

    @property
    def active_run_ids(self) -> set[str]:
        """Return the set of run IDs currently executing."""
        return set(self._active_runners.keys())

    @property
    def active_workflow_ids(self) -> set[str]:
        """Return the set of workflow IDs that have currently executing runs."""
        wf_ids: set[str] = set()
        for run_id in self._active_runners:
            run = self._store.get_run(run_id)
            if run is not None:
                wf_ids.add(run.workflow_id)
        return wf_ids

    # ------------------------------------------------------------------
    # Cron callback adapter
    # ------------------------------------------------------------------

    @staticmethod
    def is_cron_workflow_message(message: str | None) -> bool:
        """True when ``message`` is a ``__workflow__:…`` dispatch payload."""
        return isinstance(message, str) and message.startswith(_WORKFLOW_MSG_PREFIX)

    @staticmethod
    def decode_cron_message(message: str) -> tuple[str, dict[str, Any]]:
        """Reverse of :func:`_encode_cron_message`.

        Raises :class:`WorkflowServiceError` on malformed payload so the
        scheduler callback can log-and-skip rather than crash.
        """
        if not message.startswith(_WORKFLOW_MSG_PREFIX):
            raise WorkflowServiceError(
                "workflow.validation.cron_prefix: missing __workflow__: prefix"
            )
        body = message[len(_WORKFLOW_MSG_PREFIX) :]
        wf_id, _, inputs_json = body.partition(":")
        if not wf_id:
            raise WorkflowServiceError(
                "workflow.validation.cron_wf_id: workflow id is empty"
            )
        try:
            inputs = json.loads(inputs_json) if inputs_json else {}
        except json.JSONDecodeError as exc:
            raise WorkflowServiceError(
                f"workflow.validation.cron_inputs: invalid JSON ({exc.msg})"
            ) from exc
        if not isinstance(inputs, dict):
            raise WorkflowServiceError(
                "workflow.validation.cron_inputs: payload must be a JSON object"
            )
        return wf_id, inputs

    async def handle_cron_message(self, message: str) -> WorkflowRun:
        """Shortcut used by ``on_cron_job`` for messages we own."""
        wf_id, inputs = self.decode_cron_message(message)
        return await self.run(wf_id, inputs, trigger="cron")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _require_workflow(self, wf_id: str) -> Workflow:
        wf = self._store.get_workflow(wf_id)
        if wf is None:
            raise WorkflowServiceError(
                f"workflow.validation.not_found: {wf_id}"
            )
        return wf


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _encode_cron_message(wf_id: str, inputs: dict[str, Any]) -> str:
    """Build the ``__workflow__:<id>:<json>`` payload."""
    return f"{_WORKFLOW_MSG_PREFIX}{wf_id}:{json.dumps(inputs, ensure_ascii=False)}"


def _validate_workflow(wf: Workflow) -> None:
    """Cheap structural validation run before every save.

    Full semantic validation (executor reachability, schema correctness)
    lives in the runner / executors; here we only guard against shapes
    that would corrupt the JSON file or crash template resolution.
    """
    if not wf.id or not wf.id.strip():
        raise WorkflowServiceError("workflow.validation.id_required: id is empty")
    if not wf.name or not wf.name.strip():
        raise WorkflowServiceError("workflow.validation.name_required: name is empty")
    seen: set[str] = set()
    for step in wf.steps:
        if not isinstance(step, WorkflowStep):
            raise WorkflowServiceError(
                "workflow.validation.step_shape: steps must be WorkflowStep instances"
            )
        if not step.id:
            raise WorkflowServiceError(
                "workflow.validation.step_id: every step needs a non-empty id"
            )
        if step.id in seen:
            raise WorkflowServiceError(
                f"workflow.validation.step_duplicate: duplicate step id '{step.id}'"
            )
        seen.add(step.id)
        if step.kind not in ("tool", "script", "agent", "llm"):
            raise WorkflowServiceError(
                f"workflow.validation.step_kind: unknown kind '{step.kind}'"
            )
    for inp in wf.inputs:
        if not isinstance(inp, WorkflowInput):
            raise WorkflowServiceError(
                "workflow.validation.input_shape: inputs must be WorkflowInput instances"
            )
        if not inp.name or not inp.name.strip():
            raise WorkflowServiceError(
                "workflow.validation.input_name: every input needs a name"
            )

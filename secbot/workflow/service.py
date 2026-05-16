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

import json
import logging
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
        cron_service: Any = None,
        progress_cb: ProgressCallback | None = None,
        executors: dict[str, StepExecutor] | None = None,
    ) -> None:
        self._store = WorkflowStore(store_root)
        self._executors = executors or build_default_executors(
            tool_registry=tool_registry,
            agent_registry=agent_registry,
            llm_provider=llm_provider,
        )
        self._cron = cron_service
        self._progress_cb = progress_cb

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
        """Execute ``wf_id`` with ``inputs`` and return the completed run."""
        wf = self._require_workflow(wf_id)
        runner = WorkflowRunner(
            self._store, self._executors, progress_cb=self._progress_cb
        )
        return await runner.run(wf, inputs, trigger=trigger)

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

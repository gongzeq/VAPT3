"""Tests for :class:`secbot.workflow.service.WorkflowService`.

Focus areas:

* CRUD validation (``save_workflow`` rejects malformed shapes).
* Cron message encoding / decoding round-trip.
* ``attach_schedule`` / ``detach_schedule`` drive the cron service and
  mirror the cron job id into ``schedule_ref``.
* ``handle_cron_message`` dispatches to ``run``.
* ``run`` plumbs through to the runner and persists the run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from secbot.workflow import (
    StepExecutor,
    Workflow,
    WorkflowInput,
    WorkflowService,
    WorkflowServiceError,
    WorkflowStep,
)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class StubExecutor(StepExecutor):
    kind = "stub"

    def __init__(self, output: Any = None) -> None:
        self._output = output

    async def _run(self, step, args, ctx):  # noqa: ANN001
        return self._output if self._output is not None else dict(args)


class FakeCronJob:
    def __init__(self, job_id: str, message: str) -> None:
        self.id = job_id
        self.message = message


class FakeCronService:
    def __init__(self) -> None:
        self.jobs: dict[str, FakeCronJob] = {}
        self._next = 1

    def add_job(self, *, name, schedule, message, deliver=False):  # noqa: ANN001
        job_id = f"job{self._next}"
        self._next += 1
        job = FakeCronJob(job_id, message)
        self.jobs[job_id] = job
        return job

    def remove_job(self, job_id: str):
        if job_id not in self.jobs:
            return "not_found"
        del self.jobs[job_id]
        return "removed"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(tmp_path: Path, **overrides) -> WorkflowService:
    executors = overrides.pop("executors", None) or {
        "tool": StubExecutor(),
    }
    return WorkflowService(
        store_root=tmp_path / "wf",
        tool_registry=None,
        executors=executors,
        **overrides,
    )


def _sample_workflow(name: str = "demo") -> Workflow:
    return Workflow.new(
        name=name,
        inputs=[
            WorkflowInput(name="target", label="T", type="string", required=True)
        ],
        steps=[
            WorkflowStep(
                id="s1",
                name="probe",
                kind="tool",
                ref="x",
                args={"target": "${inputs.target}"},
            )
        ],
    )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def test_save_and_get_workflow(tmp_path):
    svc = _make_service(tmp_path)
    wf = _sample_workflow()
    saved = await svc.save_workflow(wf)
    assert saved.id == wf.id

    fetched = await svc.get_workflow(wf.id)
    assert fetched is not None
    assert fetched.name == "demo"


async def test_save_workflow_rejects_duplicate_step_ids(tmp_path):
    svc = _make_service(tmp_path)
    wf = Workflow.new(
        name="dup",
        steps=[
            WorkflowStep(id="s", name="a", kind="tool", ref="x"),
            WorkflowStep(id="s", name="b", kind="tool", ref="y"),
        ],
    )
    with pytest.raises(WorkflowServiceError):
        await svc.save_workflow(wf)


async def test_save_workflow_rejects_unknown_kind(tmp_path):
    svc = _make_service(tmp_path)
    wf = Workflow.new(
        name="bad",
        steps=[WorkflowStep(id="s", name="n", kind="bogus", ref="x")],  # type: ignore[arg-type]
    )
    with pytest.raises(WorkflowServiceError):
        await svc.save_workflow(wf)


async def test_delete_workflow_returns_false_when_missing(tmp_path):
    svc = _make_service(tmp_path)
    assert await svc.delete_workflow("wf_nope") is False


async def test_delete_workflow_detaches_schedule(tmp_path):
    cron = FakeCronService()
    svc = _make_service(tmp_path, cron_service=cron)
    wf = _sample_workflow()
    await svc.save_workflow(wf)
    await svc.attach_schedule(wf.id, schedule=object())

    # The schedule_ref is now populated on the stored workflow.
    assert (await svc.get_workflow(wf.id)).schedule_ref is not None
    assert cron.jobs

    assert await svc.delete_workflow(wf.id) is True
    assert cron.jobs == {}


# ---------------------------------------------------------------------------
# Cron message
# ---------------------------------------------------------------------------


def test_is_cron_workflow_message_detects_prefix():
    assert WorkflowService.is_cron_workflow_message("__workflow__:foo:{}") is True
    assert WorkflowService.is_cron_workflow_message("agent_turn hi") is False
    assert WorkflowService.is_cron_workflow_message(None) is False


def test_decode_cron_message_round_trip():
    payload = {"target": "10.0.0.1", "n": 3}
    # Re-use the private encoder to ensure we're self-consistent.
    from secbot.workflow.service import _encode_cron_message

    encoded = _encode_cron_message("wf_abc", payload)
    wf_id, inputs = WorkflowService.decode_cron_message(encoded)
    assert wf_id == "wf_abc"
    assert inputs == payload


def test_decode_cron_message_rejects_bad_json():
    with pytest.raises(WorkflowServiceError):
        WorkflowService.decode_cron_message("__workflow__:wf:{not-json")


def test_decode_cron_message_rejects_missing_prefix():
    with pytest.raises(WorkflowServiceError):
        WorkflowService.decode_cron_message("agent_turn blah")


def test_decode_cron_message_rejects_non_object_payload():
    with pytest.raises(WorkflowServiceError):
        WorkflowService.decode_cron_message("__workflow__:wf:[1,2,3]")


# ---------------------------------------------------------------------------
# Schedule sync
# ---------------------------------------------------------------------------


async def test_attach_schedule_adds_job_and_stores_ref(tmp_path):
    cron = FakeCronService()
    svc = _make_service(tmp_path, cron_service=cron)
    wf = _sample_workflow()
    await svc.save_workflow(wf)

    updated = await svc.attach_schedule(
        wf.id, schedule=object(), inputs={"target": "1.1.1.1"}
    )
    assert updated.schedule_ref is not None
    job = next(iter(cron.jobs.values()))
    assert updated.schedule_ref == job.id

    wf_id, inputs = WorkflowService.decode_cron_message(job.message)
    assert wf_id == wf.id
    assert inputs == {"target": "1.1.1.1"}


async def test_attach_schedule_replaces_existing_binding(tmp_path):
    cron = FakeCronService()
    svc = _make_service(tmp_path, cron_service=cron)
    wf = _sample_workflow()
    await svc.save_workflow(wf)

    first = await svc.attach_schedule(wf.id, schedule=object())
    second = await svc.attach_schedule(wf.id, schedule=object())
    assert first.schedule_ref != second.schedule_ref
    # Only the latest job is live.
    assert len(cron.jobs) == 1


async def test_attach_schedule_requires_cron_service(tmp_path):
    svc = _make_service(tmp_path, cron_service=None)
    wf = _sample_workflow()
    await svc.save_workflow(wf)
    with pytest.raises(WorkflowServiceError):
        await svc.attach_schedule(wf.id, schedule=object())


async def test_detach_schedule_noop_when_no_ref(tmp_path):
    cron = FakeCronService()
    svc = _make_service(tmp_path, cron_service=cron)
    wf = _sample_workflow()
    await svc.save_workflow(wf)
    updated = await svc.detach_schedule(wf.id)
    assert updated.schedule_ref is None


# ---------------------------------------------------------------------------
# Run dispatch
# ---------------------------------------------------------------------------


async def test_run_passes_inputs_to_executor_and_persists(tmp_path):
    svc = _make_service(tmp_path)
    wf = _sample_workflow()
    await svc.save_workflow(wf)

    run = await svc.run(wf.id, {"target": "10.0.0.1"}, trigger="manual")
    assert run.status == "ok"
    assert run.step_results["s1"].output == {"target": "10.0.0.1"}

    runs = await svc.list_runs(workflow_id=wf.id)
    assert [r.id for r in runs] == [run.id]
    fetched = await svc.get_run(run.id)
    assert fetched is not None
    assert fetched.trigger == "manual"


async def test_run_unknown_workflow_raises(tmp_path):
    svc = _make_service(tmp_path)
    with pytest.raises(WorkflowServiceError):
        await svc.run("wf_missing", {}, trigger="manual")


async def test_handle_cron_message_dispatches_to_run(tmp_path):
    svc = _make_service(tmp_path)
    wf = _sample_workflow()
    await svc.save_workflow(wf)

    msg = f"__workflow__:{wf.id}:{json.dumps({'target': '2.2.2.2'})}"
    run = await svc.handle_cron_message(msg)
    assert run.trigger == "cron"
    assert run.status == "ok"
    assert run.step_results["s1"].output == {"target": "2.2.2.2"}

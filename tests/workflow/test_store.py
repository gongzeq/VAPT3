"""Unit tests for :mod:`secbot.workflow.store`.

Covers the three invariants that matter for PR1:

1. ``save_workflow`` / ``get_workflow`` / ``delete_workflow`` round-trip
   through the JSON file on disk.
2. ``list_runs`` returns newest-first and honours ``workflow_id`` /
   ``limit`` filters.
3. ``upsert_run`` replaces by id (not append) and truncates to
   ``max_runs``.
"""

from __future__ import annotations

import json

import pytest

from secbot.workflow import (
    Workflow,
    WorkflowInput,
    WorkflowRun,
    WorkflowStep,
    WorkflowStore,
)
from secbot.workflow.types import StepResult


def _make_workflow(name: str = "probe") -> Workflow:
    return Workflow.new(
        name=name,
        description="demo",
        tags=["t1"],
        inputs=[WorkflowInput(name="target", label="Target", type="cidr", required=True)],
        steps=[WorkflowStep(id="s1", name="ping", kind="tool", ref="shell_tool")],
    )


def test_save_and_get_workflow_round_trip(tmp_path):
    store = WorkflowStore(tmp_path / "wf")
    wf = _make_workflow()
    store.save_workflow(wf)

    fetched = store.get_workflow(wf.id)
    assert fetched is not None
    assert fetched.id == wf.id
    assert fetched.name == "probe"
    assert fetched.inputs[0].name == "target"
    assert fetched.steps[0].kind == "tool"


def test_save_workflow_persists_camel_case_on_disk(tmp_path):
    store = WorkflowStore(tmp_path / "wf")
    wf = _make_workflow()
    store.save_workflow(wf)

    raw = json.loads((tmp_path / "wf" / "workflows.json").read_text(encoding="utf-8"))
    assert raw["version"] == 1
    item = raw["items"][0]
    assert "createdAtMs" in item
    assert "updatedAtMs" in item
    # snake_case keys must NOT leak through the wire format.
    assert "created_at_ms" not in item
    assert "on_error" not in item["steps"][0]
    assert "onError" in item["steps"][0]


def test_save_workflow_replaces_by_id(tmp_path):
    store = WorkflowStore(tmp_path / "wf")
    wf = _make_workflow("first")
    store.save_workflow(wf)

    wf.name = "renamed"
    store.save_workflow(wf)

    items = store.list_workflows()
    assert len(items) == 1
    assert items[0].name == "renamed"


def test_delete_workflow_removes_row(tmp_path):
    store = WorkflowStore(tmp_path / "wf")
    wf = _make_workflow()
    store.save_workflow(wf)

    assert store.delete_workflow(wf.id) is True
    assert store.get_workflow(wf.id) is None
    # Second delete is a no-op.
    assert store.delete_workflow(wf.id) is False


def test_list_workflows_empty_on_missing_file(tmp_path):
    store = WorkflowStore(tmp_path / "wf")
    assert store.list_workflows() == []
    assert store.get_workflow("wf_missing") is None


def test_upsert_run_replaces_existing_entry(tmp_path):
    store = WorkflowStore(tmp_path / "wf")
    wf = _make_workflow()
    store.save_workflow(wf)

    run = WorkflowRun.new(workflow_id=wf.id, inputs={"target": "10.0.0.0/24"})
    store.upsert_run(run)

    # Simulate the "finished" snapshot.
    run.status = "ok"
    run.finished_at_ms = run.started_at_ms + 500
    run.step_results["s1"] = StepResult(
        status="ok",
        started_at_ms=run.started_at_ms,
        finished_at_ms=run.finished_at_ms,
        duration_ms=500,
        output={"exit_code": 0},
    )
    store.upsert_run(run)

    runs = store.list_runs()
    assert len(runs) == 1
    assert runs[0].status == "ok"
    assert runs[0].step_results["s1"].output == {"exit_code": 0}


def test_list_runs_sorts_newest_first_and_filters(tmp_path):
    store = WorkflowStore(tmp_path / "wf")
    wf_a = _make_workflow("alpha")
    wf_b = _make_workflow("beta")
    store.save_workflow(wf_a)
    store.save_workflow(wf_b)

    run_a = WorkflowRun.new(workflow_id=wf_a.id, inputs={})
    run_a.started_at_ms = 1_000
    run_b_old = WorkflowRun.new(workflow_id=wf_b.id, inputs={})
    run_b_old.started_at_ms = 2_000
    run_b_new = WorkflowRun.new(workflow_id=wf_b.id, inputs={})
    run_b_new.started_at_ms = 3_000

    for r in (run_a, run_b_old, run_b_new):
        store.upsert_run(r)

    ordered = store.list_runs()
    assert [r.started_at_ms for r in ordered] == [3_000, 2_000, 1_000]

    only_b = store.list_runs(workflow_id=wf_b.id)
    assert [r.id for r in only_b] == [run_b_new.id, run_b_old.id]

    limited = store.list_runs(limit=2)
    assert len(limited) == 2
    assert limited[0].started_at_ms == 3_000


def test_upsert_run_truncates_to_max_runs(tmp_path):
    store = WorkflowStore(tmp_path / "wf", max_runs=3)
    wf = _make_workflow()
    store.save_workflow(wf)

    runs = []
    for i in range(5):
        r = WorkflowRun.new(workflow_id=wf.id, inputs={})
        # Force distinct, monotonically increasing timestamps.
        r.started_at_ms = 1_000 + i
        runs.append(r)
        store.upsert_run(r)

    kept = store.list_runs()
    assert len(kept) == 3
    # The three newest (started_at_ms ∈ {1002, 1003, 1004}) survive.
    assert [r.started_at_ms for r in kept] == [1_004, 1_003, 1_002]


def test_list_runs_tolerates_trailing_malformed_line(tmp_path):
    root = tmp_path / "wf"
    store = WorkflowStore(root)
    wf = _make_workflow()
    store.save_workflow(wf)

    good = WorkflowRun.new(workflow_id=wf.id, inputs={})
    good.started_at_ms = 5_000
    store.upsert_run(good)

    # Simulate a crash that left a half-written row at EOF.
    with open(root / "runs.jsonl", "a", encoding="utf-8") as f:
        f.write('{"id": "run_bad", "workflow_id":\n')

    runs = store.list_runs()
    assert [r.id for r in runs] == [good.id]


def test_get_run_returns_none_when_missing(tmp_path):
    store = WorkflowStore(tmp_path / "wf")
    assert store.get_run("run_does_not_exist") is None


def test_get_run_returns_specific_row(tmp_path):
    store = WorkflowStore(tmp_path / "wf")
    wf = _make_workflow()
    store.save_workflow(wf)
    r = WorkflowRun.new(workflow_id=wf.id, inputs={"k": "v"})
    store.upsert_run(r)

    fetched = store.get_run(r.id)
    assert fetched is not None
    assert fetched.inputs == {"k": "v"}


@pytest.mark.parametrize("method", ["list_workflows", "list_runs"])
def test_empty_store_methods_return_empty_list(tmp_path, method):
    store = WorkflowStore(tmp_path / "wf")
    assert getattr(store, method)() == []

"""Tests for :mod:`secbot.workflow.types` — dataclasses + camelCase round-trip."""

from __future__ import annotations

from secbot.workflow.types import (
    StepResult,
    Workflow,
    WorkflowInput,
    WorkflowRun,
    WorkflowStep,
)


def _build_workflow() -> Workflow:
    return Workflow.new(
        name="内网扫描",
        description="每日 09:00 扫描 C 段",
        tags=["recon", "daily"],
        inputs=[
            WorkflowInput(
                name="param_a",
                label="自定义入参 A",
                type="string",
                required=True,
            ),
            WorkflowInput(
                name="param_b",
                label="自定义枚举 B",
                type="enum",
                default="b",
                enum_values=["a", "b", "c"],
            ),
        ],
        steps=[
            WorkflowStep(id="s1", name="读日志", kind="tool", ref="file_read",
                         args={"path": "${inputs.param_a}"}),
            WorkflowStep(id="s2", name="筛错", kind="script", ref="python",
                         args={"code": "print(1)"}, on_error="continue", retry=2),
        ],
    )


def test_workflow_new_assigns_id_and_timestamps() -> None:
    wf = _build_workflow()
    assert wf.id.startswith("wf_") and len(wf.id) == 11
    assert wf.created_at_ms > 0
    assert wf.updated_at_ms == wf.created_at_ms
    assert len(wf.steps) == 2


def test_workflow_to_dict_uses_camel_case() -> None:
    wf = _build_workflow()
    raw = wf.to_dict()
    assert "createdAtMs" in raw and "updatedAtMs" in raw
    assert "created_at_ms" not in raw
    assert raw["inputs"][1]["enumValues"] == ["a", "b", "c"]
    assert raw["steps"][1]["onError"] == "continue"


def test_workflow_from_dict_round_trip_camel() -> None:
    wf = _build_workflow()
    restored = Workflow.from_dict(wf.to_dict())
    assert restored.id == wf.id
    assert restored.name == wf.name
    assert [i.enum_values for i in restored.inputs] == [None, ["a", "b", "c"]]
    assert restored.steps[1].on_error == "continue"


def test_workflow_from_dict_accepts_snake_case() -> None:
    wf = _build_workflow()
    # Legacy / pytest fixture shape where callers hand-built snake_case dicts.
    restored = Workflow.from_dict(
        {
            "id": wf.id,
            "name": wf.name,
            "description": "",
            "tags": [],
            "inputs": [
                {"name": "x", "label": "X", "type": "int", "required": False,
                 "default": None, "enum_values": None}
            ],
            "steps": [
                {"id": "s1", "name": "s1", "kind": "tool", "ref": "file_read",
                 "args": {}, "condition": None, "on_error": "stop", "retry": 0}
            ],
            "schedule_ref": None,
            "created_at_ms": wf.created_at_ms,
            "updated_at_ms": wf.updated_at_ms,
        }
    )
    assert restored.inputs[0].type == "int"
    assert restored.steps[0].kind == "tool"


def test_workflow_run_round_trip_and_step_result() -> None:
    wf = _build_workflow()
    run = WorkflowRun.new(workflow_id=wf.id, inputs={"param_a": "/tmp/a.log"})
    run.step_results["s1"] = StepResult(
        status="ok",
        started_at_ms=run.started_at_ms,
        finished_at_ms=run.started_at_ms + 100,
        duration_ms=100,
        output={"content": "hello"},
    )
    run.step_results["s2"] = StepResult.skipped(at_ms=run.started_at_ms + 100)
    run.status = "ok"
    run.finished_at_ms = run.started_at_ms + 200

    payload = run.to_dict()
    assert payload["stepResults"]["s1"]["durationMs"] == 100
    assert payload["stepResults"]["s2"]["status"] == "skipped"
    assert payload["workflowId"] == wf.id

    restored = WorkflowRun.from_dict(payload)
    assert restored.status == "ok"
    assert restored.step_results["s1"].output == {"content": "hello"}
    assert restored.step_results["s2"].status == "skipped"
    assert restored.trigger == "manual"

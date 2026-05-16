"""Tests for :class:`secbot.workflow.runner.WorkflowRunner`.

Covered behaviours:

* Happy path: step result feeds into downstream template interpolation.
* ``condition`` skips a step and records ``status=skipped``.
* ``retry`` on error + ``status=retried`` on eventual success.
* ``on_error=stop`` aborts the run; ``on_error=continue`` keeps going.
* Unknown ``step.kind`` becomes a step error, not an engine crash.
* ``input_missing`` for required inputs raises :class:`RunnerError`.
* Progress callback fires for every lifecycle transition.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from secbot.workflow import (
    RunnerError,
    StepExecutor,
    Workflow,
    WorkflowInput,
    WorkflowRunner,
    WorkflowStep,
    WorkflowStore,
)
from secbot.workflow.executors.base import ExecutorError


class ProgrammableExecutor(StepExecutor):
    kind = "programmable"

    def __init__(self, behaviours: list[Any]) -> None:
        self._behaviours = behaviours or []
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def _run(self, step, args, ctx):  # noqa: ANN001
        self.calls.append((step.id, dict(args)))
        i = min(len(self.calls) - 1, len(self._behaviours) - 1)
        behaviour = self._behaviours[i]
        if callable(behaviour):
            return behaviour(step, args, ctx)
        return behaviour


def _make_wf(
    steps: list[WorkflowStep],
    inputs: list[WorkflowInput] | None = None,
) -> Workflow:
    return Workflow.new(name="t", inputs=inputs or [], steps=steps)


def _store(tmp_path: Path) -> WorkflowStore:
    return WorkflowStore(tmp_path / "wf")


# ---------------------------------------------------------------------------
# Happy path + interpolation
# ---------------------------------------------------------------------------


async def test_runner_interpolates_args_from_inputs_and_prior_steps(tmp_path):
    captured: list[dict[str, Any]] = []

    def echo(step, args, ctx):  # noqa: ANN001
        captured.append(dict(args))
        return {"seen": args}

    execu = ProgrammableExecutor([lambda s, a, c: {"value": 42}, echo])
    wf = _make_wf(
        [
            WorkflowStep(id="s1", name="prod", kind="tool", ref="x"),
            WorkflowStep(
                id="s2",
                name="cons",
                kind="tool",
                ref="y",
                args={
                    "from_input": "${inputs.target}",
                    "from_step": "${steps.s1.result.value}",
                    "literal": "plain",
                },
            ),
        ],
        inputs=[WorkflowInput(name="target", label="T", type="string")],
    )
    store = _store(tmp_path)
    store.save_workflow(wf)

    runner = WorkflowRunner(store, {"tool": execu})
    run = await runner.run(wf, {"target": "10.0.0.1"})

    assert run.status == "ok"
    assert captured[0] == {
        "from_input": "10.0.0.1",
        "from_step": 42,
        "literal": "plain",
    }
    assert run.step_results["s2"].output == {
        "seen": {"from_input": "10.0.0.1", "from_step": 42, "literal": "plain"},
    }


# ---------------------------------------------------------------------------
# Condition
# ---------------------------------------------------------------------------


async def test_runner_skips_step_when_condition_false(tmp_path):
    calls: list[str] = []

    def rec(step, args, ctx):  # noqa: ANN001
        calls.append(step.id)
        return {"ok": True}

    execu = ProgrammableExecutor([rec])
    wf = _make_wf(
        [
            WorkflowStep(
                id="guarded",
                name="n",
                kind="tool",
                ref="x",
                condition="inputs.enable == True",
            )
        ],
        inputs=[WorkflowInput(name="enable", label="E", type="bool")],
    )
    store = _store(tmp_path)
    store.save_workflow(wf)
    runner = WorkflowRunner(store, {"tool": execu})

    run = await runner.run(wf, {"enable": False})
    assert calls == []
    assert run.step_results["guarded"].status == "skipped"


async def test_runner_reports_bad_condition_as_skip_with_reason(tmp_path):
    events: list[tuple[str, dict[str, Any]]] = []

    async def cb(event, payload):
        events.append((event, payload))

    wf = _make_wf(
        [
            WorkflowStep(
                id="bad",
                name="n",
                kind="tool",
                ref="x",
                # ``__import__`` is rejected by the expression sandbox.
                condition="__import__('os')",
            )
        ]
    )
    store = _store(tmp_path)
    store.save_workflow(wf)
    runner = WorkflowRunner(
        store, {"tool": ProgrammableExecutor([None])}, progress_cb=cb
    )

    run = await runner.run(wf, {})
    assert run.step_results["bad"].status == "skipped"
    finished = [p for e, p in events if e == "workflow.step.finished"]
    assert any(
        p.get("skippedReason", "").startswith("condition_error") for p in finished
    )


# ---------------------------------------------------------------------------
# Retry + on_error
# ---------------------------------------------------------------------------


async def test_runner_retries_and_marks_status_retried(tmp_path, monkeypatch):
    import secbot.workflow.runner as runner_mod

    monkeypatch.setattr(runner_mod, "_RETRY_BACKOFF_S", 0)

    def flaky(step, args, ctx):  # noqa: ANN001
        flaky.n += 1  # type: ignore[attr-defined]
        if flaky.n < 3:  # type: ignore[attr-defined]
            raise ExecutorError("transient")
        return {"ok": True}

    flaky.n = 0  # type: ignore[attr-defined]

    execu = ProgrammableExecutor([flaky])
    wf = _make_wf([WorkflowStep(id="s", name="n", kind="tool", ref="x", retry=3)])
    store = _store(tmp_path)
    store.save_workflow(wf)
    runner = WorkflowRunner(store, {"tool": execu})

    run = await runner.run(wf, {})
    assert run.status == "ok"
    assert run.step_results["s"].status == "retried"
    assert run.step_results["s"].output == {"ok": True}
    assert flaky.n == 3  # type: ignore[attr-defined]


async def test_runner_retry_exhaustion_yields_error(tmp_path, monkeypatch):
    import secbot.workflow.runner as runner_mod

    monkeypatch.setattr(runner_mod, "_RETRY_BACKOFF_S", 0)

    def always_fail(step, args, ctx):  # noqa: ANN001
        raise ExecutorError("nope")

    execu = ProgrammableExecutor([always_fail])
    wf = _make_wf([WorkflowStep(id="s", name="n", kind="tool", ref="x", retry=2)])
    store = _store(tmp_path)
    store.save_workflow(wf)
    runner = WorkflowRunner(store, {"tool": execu})

    run = await runner.run(wf, {})
    assert run.status == "error"
    assert run.step_results["s"].status == "error"
    assert "nope" in (run.step_results["s"].error or "")


async def test_runner_on_error_continue_keeps_executing(tmp_path, monkeypatch):
    import secbot.workflow.runner as runner_mod

    monkeypatch.setattr(runner_mod, "_RETRY_BACKOFF_S", 0)

    def fail(step, args, ctx):  # noqa: ANN001
        raise ExecutorError("boom")

    def ok(step, args, ctx):  # noqa: ANN001
        return {"ran": True}

    fail_execu = ProgrammableExecutor([fail])
    ok_execu = ProgrammableExecutor([ok])
    wf = _make_wf(
        [
            WorkflowStep(
                id="s1", name="n1", kind="fail", ref="x", on_error="continue"
            ),
            WorkflowStep(id="s2", name="n2", kind="ok", ref="y"),
        ]
    )
    store = _store(tmp_path)
    store.save_workflow(wf)
    runner = WorkflowRunner(store, {"fail": fail_execu, "ok": ok_execu})

    run = await runner.run(wf, {})
    assert run.status == "ok"
    assert run.step_results["s1"].status == "error"
    assert run.step_results["s2"].status == "ok"


async def test_runner_on_error_stop_aborts_subsequent_steps(tmp_path):
    def fail(step, args, ctx):  # noqa: ANN001
        raise ExecutorError("halt")

    def should_not_run(step, args, ctx):  # noqa: ANN001
        raise AssertionError("downstream step ran despite on_error=stop")

    fail_execu = ProgrammableExecutor([fail])
    ok_execu = ProgrammableExecutor([should_not_run])
    wf = _make_wf(
        [
            WorkflowStep(id="s1", name="n1", kind="fail", ref="x", on_error="stop"),
            WorkflowStep(id="s2", name="n2", kind="ok", ref="y"),
        ]
    )
    store = _store(tmp_path)
    store.save_workflow(wf)
    runner = WorkflowRunner(store, {"fail": fail_execu, "ok": ok_execu})

    run = await runner.run(wf, {})
    assert run.status == "error"
    assert run.error is not None and "s1" in run.error
    assert "s2" not in run.step_results


# ---------------------------------------------------------------------------
# Miscellaneous
# ---------------------------------------------------------------------------


async def test_runner_unknown_kind_is_step_error(tmp_path):
    wf = _make_wf(
        [WorkflowStep(id="s", name="n", kind="tool", ref="x")]
    )
    store = _store(tmp_path)
    store.save_workflow(wf)
    runner = WorkflowRunner(store, {})  # no executor wired
    run = await runner.run(wf, {})
    assert run.status == "error"
    assert "kind_unknown" in (run.step_results["s"].error or "")


async def test_runner_missing_required_input_raises_before_run_creation(tmp_path):
    wf = _make_wf(
        [WorkflowStep(id="s", name="n", kind="tool", ref="x")],
        inputs=[
            WorkflowInput(name="target", label="T", type="string", required=True)
        ],
    )
    store = _store(tmp_path)
    store.save_workflow(wf)
    runner = WorkflowRunner(store, {"tool": ProgrammableExecutor([None])})
    with pytest.raises(RunnerError):
        await runner.run(wf, {})
    # Nothing was persisted because validation blows up before new().
    assert store.list_runs() == []


async def test_runner_fires_all_progress_events(tmp_path):
    events: list[str] = []

    async def cb(event, payload):
        events.append(event)

    def ok(step, args, ctx):  # noqa: ANN001
        return {}

    wf = _make_wf([WorkflowStep(id="s", name="n", kind="tool", ref="x")])
    store = _store(tmp_path)
    store.save_workflow(wf)
    runner = WorkflowRunner(
        store, {"tool": ProgrammableExecutor([ok])}, progress_cb=cb
    )
    await runner.run(wf, {})
    assert events == [
        "workflow.run.started",
        "workflow.step.started",
        "workflow.step.finished",
        "workflow.run.finished",
    ]


async def test_runner_env_snapshot_available_in_templates(tmp_path):
    captured: dict[str, Any] = {}

    def rec(step, args, ctx):  # noqa: ANN001
        captured.update(args)
        return {}

    wf = _make_wf(
        [
            WorkflowStep(
                id="s",
                name="n",
                kind="tool",
                ref="x",
                args={"home": "${env.WF_HOME}"},
            )
        ]
    )
    store = _store(tmp_path)
    store.save_workflow(wf)
    runner = WorkflowRunner(
        store,
        {"tool": ProgrammableExecutor([rec])},
        env_snapshot={"WF_HOME": "/tmp/wf"},
    )
    await runner.run(wf, {})
    assert captured == {"home": "/tmp/wf"}


async def test_runner_progress_cb_exception_does_not_break_run(tmp_path):
    async def crashy(event, payload):
        raise RuntimeError("subscriber fail")

    def ok(step, args, ctx):  # noqa: ANN001
        return {"x": 1}

    wf = _make_wf([WorkflowStep(id="s", name="n", kind="tool", ref="x")])
    store = _store(tmp_path)
    store.save_workflow(wf)
    runner = WorkflowRunner(
        store, {"tool": ProgrammableExecutor([ok])}, progress_cb=crashy
    )
    run = await runner.run(wf, {})
    assert run.status == "ok"

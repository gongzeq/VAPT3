"""Subagent ``tool_call`` agent_event broadcast tests.

Spec: ``.trellis/tasks/05-12-multi-agent-obs-tool-call/prd.md`` §B5.

Exercises :class:`secbot.agent.subagent._SubagentHook` in isolation — we
synthesise :class:`AgentHookContext` objects that mirror what the runner
produces, then assert the hook emits the right ``tool_call`` frames.

Covered cases:
    - Non-critical tool: running → ok
    - Failed tool: running → error
    - Critical skill approved: critical → ok
    - Critical skill denied: critical → error(reason=user_denied)
    - Critical skill timeout: critical → error(reason=timeout)
    - Default hook without broadcast_fn stays silent (backward-compat).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest

from secbot.agent.hook import AgentHookContext
from secbot.agent.subagent import SubagentStatus, _SubagentHook


@dataclass
class _FakeToolCall:
    """Minimal stand-in for :class:`ToolCallRequest`.

    The hook only touches ``id``, ``name`` and ``arguments`` — we avoid
    importing the provider layer to keep the unit test hermetic.
    """

    id: str
    name: str
    arguments: dict[str, Any]


def _make_hook(
    *,
    critical: set[str] | None = None,
) -> tuple[_SubagentHook, list[tuple[str, dict[str, Any]]]]:
    captured: list[tuple[str, dict[str, Any]]] = []

    async def _broadcast(type_: str, payload: dict[str, Any]) -> None:
        captured.append((type_, payload))

    status = SubagentStatus(
        task_id="task-1",
        label="port-scanner",
        task_description="scan target",
        started_at=0.0,
    )
    hook = _SubagentHook(
        "task-1",
        status,
        broadcast_fn=_broadcast,
        agent_name="port-scanner",
        critical_tool_names=critical or set(),
    )
    return hook, captured


@pytest.mark.asyncio
async def test_non_critical_tool_running_then_ok():
    hook, captured = _make_hook()
    call = _FakeToolCall(id="c1", name="read_file", arguments={"path": "x"})

    ctx_before = AgentHookContext(iteration=1, messages=[], tool_calls=[call])
    await hook.before_execute_tools(ctx_before)

    ctx_after = AgentHookContext(
        iteration=1,
        messages=[],
        tool_calls=[call],
        tool_results=["file contents"],
        tool_events=[{"name": "read_file", "status": "ok", "detail": "ok"}],
    )
    await hook.after_iteration(ctx_after)

    assert [(t, p["status"]) for t, p in captured] == [
        ("tool_call", "running"),
        ("tool_call", "ok"),
    ]
    running = captured[0][1]
    ok = captured[1][1]
    assert running["tool_call_id"] == "c1"
    assert running["tool_name"] == "read_file"
    assert running["tool_args"] == {"path": "x"}
    assert running["is_critical"] is False
    assert ok["tool_call_id"] == "c1"
    assert ok["is_critical"] is False
    assert "duration_ms" in ok
    assert "reason" not in ok


@pytest.mark.asyncio
async def test_failed_tool_broadcasts_error():
    hook, captured = _make_hook()
    call = _FakeToolCall(id="c2", name="exec", arguments={"cmd": "oops"})

    await hook.before_execute_tools(
        AgentHookContext(iteration=1, messages=[], tool_calls=[call])
    )
    await hook.after_iteration(
        AgentHookContext(
            iteration=1,
            messages=[],
            tool_calls=[call],
            tool_results=["Error: RuntimeError: boom"],
            tool_events=[
                {"name": "exec", "status": "error", "detail": "RuntimeError: boom"}
            ],
        )
    )

    statuses = [p["status"] for _, p in captured]
    assert statuses == ["running", "error"]
    err = captured[1][1]
    assert err["detail"] == "RuntimeError: boom"
    assert "reason" not in err  # non-user-denied errors carry no reason


@pytest.mark.asyncio
async def test_critical_skill_approved_critical_then_ok():
    hook, captured = _make_hook(critical={"sqlmap-dump"})
    call = _FakeToolCall(id="c3", name="sqlmap-dump", arguments={"url": "http://x"})

    await hook.before_execute_tools(
        AgentHookContext(iteration=1, messages=[], tool_calls=[call])
    )
    # Approved → HighRiskGate runs the handler and returns a normal SkillResult.
    approved_result = json.dumps(
        {
            "skill": "sqlmap-dump",
            "summary": {"tables": ["users"]},
            "raw_log_path": None,
            "findings": [],
            "cmdb_writes": [],
        }
    )
    await hook.after_iteration(
        AgentHookContext(
            iteration=1,
            messages=[],
            tool_calls=[call],
            tool_results=[approved_result],
            tool_events=[{"name": "sqlmap-dump", "status": "ok", "detail": "ok"}],
        )
    )

    statuses = [p["status"] for _, p in captured]
    assert statuses == ["critical", "ok"]
    assert captured[0][1]["is_critical"] is True
    assert captured[1][1]["is_critical"] is True
    assert "reason" not in captured[1][1]


@pytest.mark.asyncio
async def test_critical_skill_denied_emits_user_denied_reason():
    hook, captured = _make_hook(critical={"hydra-bruteforce"})
    call = _FakeToolCall(
        id="c4", name="hydra-bruteforce", arguments={"target": "1.1.1.1"}
    )

    await hook.before_execute_tools(
        AgentHookContext(iteration=1, messages=[], tool_calls=[call])
    )
    # HighRiskGate returns SkillResult(summary={"user_denied": True, "reason":
    # "denied"}) which _result_payload wraps into JSON.
    denied_result = json.dumps(
        {
            "skill": "hydra-bruteforce",
            "summary": {"user_denied": True, "reason": "denied"},
            "raw_log_path": None,
            "findings": [],
            "cmdb_writes": [],
        }
    )
    await hook.after_iteration(
        AgentHookContext(
            iteration=1,
            messages=[],
            tool_calls=[call],
            tool_results=[denied_result],
            tool_events=[
                {"name": "hydra-bruteforce", "status": "ok", "detail": "ok"}
            ],
        )
    )

    assert [p["status"] for _, p in captured] == ["critical", "error"]
    terminal = captured[1][1]
    assert terminal["reason"] == "user_denied"
    assert terminal["is_critical"] is True


@pytest.mark.asyncio
async def test_critical_skill_timeout_emits_timeout_reason():
    hook, captured = _make_hook(critical={"hydra-bruteforce"})
    call = _FakeToolCall(
        id="c5", name="hydra-bruteforce", arguments={"target": "1.1.1.1"}
    )

    await hook.before_execute_tools(
        AgentHookContext(iteration=1, messages=[], tool_calls=[call])
    )
    timeout_result = json.dumps(
        {
            "skill": "hydra-bruteforce",
            "summary": {"user_denied": True, "reason": "confirm_timeout"},
            "raw_log_path": None,
            "findings": [],
            "cmdb_writes": [],
        }
    )
    await hook.after_iteration(
        AgentHookContext(
            iteration=1,
            messages=[],
            tool_calls=[call],
            tool_results=[timeout_result],
            tool_events=[
                {"name": "hydra-bruteforce", "status": "ok", "detail": "ok"}
            ],
        )
    )

    statuses_reasons = [(p["status"], p.get("reason")) for _, p in captured]
    assert statuses_reasons == [
        ("critical", None),
        ("error", "timeout"),
    ]


@pytest.mark.asyncio
async def test_waiting_event_is_skipped_until_terminal():
    """AskUserTool produces status=waiting; no terminal frame should fire yet."""
    hook, captured = _make_hook()
    call = _FakeToolCall(id="c6", name="ask_user", arguments={"prompt": "ok?"})

    await hook.before_execute_tools(
        AgentHookContext(iteration=1, messages=[], tool_calls=[call])
    )
    await hook.after_iteration(
        AgentHookContext(
            iteration=1,
            messages=[],
            tool_calls=[call],
            tool_results=[""],
            tool_events=[{"name": "ask_user", "status": "waiting", "detail": ""}],
        )
    )

    # Only the initial running frame — the terminal is deferred.
    assert [p["status"] for _, p in captured] == ["running"]


@pytest.mark.asyncio
async def test_default_hook_without_broadcast_stays_silent():
    """Backward compat: constructing the hook without broadcast_fn is a noop."""
    hook = _SubagentHook("task-noop")
    call = _FakeToolCall(id="c7", name="read_file", arguments={})

    # Must not raise; _start_times still populated for status mirroring.
    await hook.before_execute_tools(
        AgentHookContext(iteration=1, messages=[], tool_calls=[call])
    )
    await hook.after_iteration(
        AgentHookContext(
            iteration=1,
            messages=[],
            tool_calls=[call],
            tool_results=["ok"],
            tool_events=[{"name": "read_file", "status": "ok", "detail": "ok"}],
        )
    )


@pytest.mark.asyncio
async def test_multiple_tools_in_one_iteration_paired_by_index():
    """Parallel tool batches produce one running/terminal pair per tool_call."""
    hook, captured = _make_hook(critical={"sqlmap-dump"})
    calls = [
        _FakeToolCall(id="a", name="read_file", arguments={"path": "p"}),
        _FakeToolCall(id="b", name="sqlmap-dump", arguments={"url": "u"}),
    ]
    approved = json.dumps(
        {
            "skill": "sqlmap-dump",
            "summary": {"tables": []},
            "raw_log_path": None,
            "findings": [],
            "cmdb_writes": [],
        }
    )

    await hook.before_execute_tools(
        AgentHookContext(iteration=1, messages=[], tool_calls=calls)
    )
    await hook.after_iteration(
        AgentHookContext(
            iteration=1,
            messages=[],
            tool_calls=calls,
            tool_results=["file", approved],
            tool_events=[
                {"name": "read_file", "status": "ok", "detail": "ok"},
                {"name": "sqlmap-dump", "status": "ok", "detail": "ok"},
            ],
        )
    )

    # 2 running (one per call, in order) + 2 terminal (one per call).
    assert [(p["tool_call_id"], p["status"]) for _, p in captured] == [
        ("a", "running"),
        ("b", "critical"),
        ("a", "ok"),
        ("b", "ok"),
    ]
    # critical flag tracks is_critical per tool, not per batch.
    flags = {p["tool_call_id"]: p["is_critical"] for _, p in captured}
    assert flags == {"a": False, "b": True}

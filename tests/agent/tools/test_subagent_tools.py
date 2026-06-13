"""Tests for subagent tool registration and wiring."""

import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from secbot.config.schema import AgentDefaults

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars


@pytest.mark.asyncio
async def test_subagent_result_event_uses_agent_name_not_response(tmp_path):
    """Lifecycle event titles key off the expert agent name, not label/result text."""
    from secbot.agent.subagent import SubagentManager
    from secbot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    )
    mgr._broadcast_agent_event = AsyncMock()

    await mgr._announce_result(
        "sub-1",
        "The subagent response was accidentally placed here.",
        "scan target",
        "Actual response body",
        {"channel": "websocket", "chat_id": "c1", "session_key": "websocket:c1"},
        "ok",
        agent_name="port_scan",
    )

    msg = await bus.consume_inbound()
    assert msg.sender_id == "port_scan"

    kwargs = mgr._broadcast_agent_event.await_args.kwargs
    assert kwargs["type"] == "subagent_done"
    assert kwargs["payload"]["agent_name"] == "port_scan"
    assert kwargs["payload"]["label"] == "The subagent response was accidentally placed here."
    assert kwargs["payload"]["result"] == "Actual response body"


@pytest.mark.asyncio
async def test_subagent_never_registers_exec_tool(tmp_path):
    """Ad-hoc subagents (no expert spec) must NEVER receive ExecTool.

    ExecTool is gated by BOTH global exec_config.enable AND per-agent
    allow_exec. Ad-hoc subagents have no spec, so they can never qualify.
    """
    from secbot.agent.subagent import SubagentManager, SubagentStatus
    from secbot.bus.queue import MessageBus
    from secbot.config.schema import ExecToolConfig

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        exec_config=ExecToolConfig(enable=True, allowed_env_keys=["GOPATH"]),
    )
    mgr._announce_result = AsyncMock()

    async def fake_run(spec):
        assert spec.tools.get("exec") is None, (
            "ExecTool leaked into ad-hoc subagent — must require expert spec with allow_exec"
        )
        return SimpleNamespace(
            stop_reason="done",
            final_content="done",
            error=None,
            tool_events=[],
        )

    mgr.runner.run = AsyncMock(side_effect=fake_run)

    status = SubagentStatus(
        task_id="sub-1", label="label", task_description="do task", started_at=time.monotonic()
    )
    await mgr._run_subagent(
        "sub-1", "do task", "label", {"channel": "test", "chat_id": "c1"}, status
    )

    mgr.runner.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_subagent_registers_exec_when_agent_opted_in(tmp_path):
    """Subagents spawned with allow_exec=True DO receive ExecTool when globally enabled."""
    from secbot.agent.subagent import SubagentManager, SubagentStatus
    from secbot.agents.registry import ExpertAgentSpec
    from secbot.bus.queue import MessageBus
    from secbot.config.schema import ExecToolConfig

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        exec_config=ExecToolConfig(enable=True),
    )
    mgr._announce_result = AsyncMock()

    spec = ExpertAgentSpec(
        name="vuln_detec",
        display_name="Vuln Detec",
        description="test",
        system_prompt="test",
        scoped_skills=("vuln-detec-manual",),
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        allow_exec=True,
    )

    async def fake_run(run_spec):
        assert run_spec.tools.get("exec") is not None, (
            "ExecTool missing for allow_exec=True agent"
        )
        return SimpleNamespace(
            stop_reason="done",
            final_content="done",
            error=None,
            tool_events=[],
        )

    mgr.runner.run = AsyncMock(side_effect=fake_run)

    status = SubagentStatus(
        task_id="sub-1", label="label", task_description="do task", started_at=time.monotonic()
    )
    await mgr._run_subagent(
        "sub-1", "do task", "label", {"channel": "test", "chat_id": "c1"}, status, None, spec
    )

    mgr.runner.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_subagent_with_allow_exec_false_still_blocked(tmp_path):
    """Even with global exec_config.enable=True, allow_exec=False blocks ExecTool."""
    from secbot.agent.subagent import SubagentManager, SubagentStatus
    from secbot.agents.registry import ExpertAgentSpec
    from secbot.bus.queue import MessageBus
    from secbot.config.schema import ExecToolConfig

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        exec_config=ExecToolConfig(enable=True),
    )
    mgr._announce_result = AsyncMock()

    spec = ExpertAgentSpec(
        name="port_scan",
        display_name="Port Scan",
        description="test",
        system_prompt="test",
        scoped_skills=("qscan-port-scan",),
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        allow_exec=False,
    )

    async def fake_run(run_spec):
        assert run_spec.tools.get("exec") is None, (
            "ExecTool must be blocked for allow_exec=False agent"
        )
        return SimpleNamespace(
            stop_reason="done",
            final_content="done",
            error=None,
            tool_events=[],
        )

    mgr.runner.run = AsyncMock(side_effect=fake_run)

    status = SubagentStatus(
        task_id="sub-1", label="label", task_description="do task", started_at=time.monotonic()
    )
    await mgr._run_subagent(
        "sub-1", "do task", "label", {"channel": "test", "chat_id": "c1"}, status, None, spec
    )

    mgr.runner.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_subagent_uses_configured_max_iterations(tmp_path):
    """Subagents should honor the configured tool-iteration limit."""
    from secbot.agent.subagent import SubagentManager, SubagentStatus
    from secbot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        max_iterations=37,
    )
    mgr._announce_result = AsyncMock()

    async def fake_run(spec):
        assert spec.max_iterations == 37
        return SimpleNamespace(
            stop_reason="done",
            final_content="done",
            error=None,
            tool_events=[],
        )

    mgr.runner.run = AsyncMock(side_effect=fake_run)

    status = SubagentStatus(
        task_id="sub-1", label="label", task_description="do task", started_at=time.monotonic()
    )
    await mgr._run_subagent(
        "sub-1", "do task", "label", {"channel": "test", "chat_id": "c1"}, status
    )

    mgr.runner.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_spawn_tool_rejects_when_at_concurrency_limit(tmp_path):
    """SpawnTool should return an error string when the concurrency limit is reached."""
    from secbot.agent.subagent import SubagentManager
    from secbot.agent.tools.spawn import SpawnTool
    from secbot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    )
    mgr._announce_result = AsyncMock()

    # Attach a minimal fake registry so create_agent passes name validation
    fake_spec = SimpleNamespace(available=True, endpoint_bound=False, missing_binaries=[])
    fake_registry = MagicMock()
    fake_registry.__contains__ = lambda self, n: n == "port_scan"
    fake_registry.get = MagicMock(return_value=fake_spec)
    fake_registry.names = MagicMock(return_value=["port_scan"])
    mgr.agent_registry = fake_registry

    # Block the first subagent so it stays "running"
    release = asyncio.Event()

    async def fake_run(spec):
        await release.wait()
        return SimpleNamespace(
            stop_reason="done",
            final_content="done",
            error=None,
            tool_events=[],
        )

    mgr.runner.run = AsyncMock(side_effect=fake_run)

    tool = SpawnTool(mgr)
    tool.set_context("test", "c1", "test:c1")

    # First spawn succeeds
    result = await tool.execute(name="port_scan", task="first task", target="10.0.0.1")
    assert "started" in result

    # Second spawn should be rejected (default limit is 1)
    result = await tool.execute(name="port_scan", task="second task", target="10.0.0.2")
    assert "Cannot spawn subagent" in result
    assert "concurrency limit reached" in result

    # Release the first subagent
    release.set()
    # Allow cleanup
    await asyncio.gather(*mgr._running_tasks.values(), return_exceptions=True)


def test_subagent_default_max_concurrent_matches_agent_defaults(tmp_path):
    """Direct SubagentManager construction should use the agent default concurrency limit."""
    from secbot.agent.subagent import SubagentManager
    from secbot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    )

    assert mgr.max_concurrent_subagents == AgentDefaults().max_concurrent_subagents


def test_subagent_default_max_iterations_matches_agent_defaults(tmp_path):
    """Direct SubagentManager construction should use the agent default limit."""
    from secbot.agent.subagent import SubagentManager
    from secbot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    )

    assert mgr.max_iterations == AgentDefaults().max_tool_iterations


def test_agent_loop_passes_max_iterations_to_subagents(tmp_path):
    """AgentLoop's configured limit should be shared with spawned subagents."""
    from secbot.agent.loop import AgentLoop
    from secbot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        max_iterations=42,
    )

    assert loop.subagents.max_iterations == 42


def test_agent_loop_registers_subagent_lifecycle_tools(tmp_path):
    """The orchestrator should expose explicit subagent wait/check tools."""
    from secbot.agent.loop import AgentLoop
    from secbot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        is_orchestrator=True,
    )

    assert loop.tools.get("check_subagents") is not None
    assert loop.tools.get("wait_subagent") is not None


@pytest.mark.asyncio
async def test_agent_loop_syncs_updated_max_iterations_before_run(tmp_path):
    """Runtime max_iterations changes should be reflected before tool execution."""
    from secbot.agent.loop import AgentLoop
    from secbot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        max_iterations=42,
    )
    loop.tools.get_definitions = MagicMock(return_value=[])

    async def fake_run(spec):
        assert spec.max_iterations == 55
        assert loop.subagents.max_iterations == 55
        return SimpleNamespace(
            stop_reason="done",
            final_content="done",
            error=None,
            tool_events=[],
            messages=[],
            usage={},
            had_injections=False,
            tools_used=[],
        )

    loop.runner.run = AsyncMock(side_effect=fake_run)
    loop.max_iterations = 55

    await loop._run_agent_loop([])

    loop.runner.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_subagents_tool_filters_current_session(tmp_path):
    """check_subagents should report only the active session's retained statuses."""
    from secbot.agent.subagent import SubagentManager, SubagentStatus
    from secbot.agent.tools.subagents import CheckSubagentsTool
    from secbot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    )

    async def _hang_forever():
        await asyncio.Event().wait()

    running_task = asyncio.create_task(_hang_forever())
    mgr._running_tasks["sub-1"] = running_task
    mgr._session_tasks.setdefault("test:c1", set()).add("sub-1")
    mgr._task_statuses["sub-1"] = SubagentStatus(
        task_id="sub-1",
        label="running",
        task_description="do running work",
        started_at=time.monotonic(),
        agent_name="vuln_scan",
        session_key="test:c1",
    )
    mgr._task_statuses["sub-2"] = SubagentStatus(
        task_id="sub-2",
        label="completed",
        task_description="done work",
        started_at=time.monotonic(),
        phase="done",
        stop_reason="completed",
        agent_name="report",
        session_key="test:c1",
    )
    mgr._task_statuses["other"] = SubagentStatus(
        task_id="other",
        label="other",
        task_description="other work",
        started_at=time.monotonic(),
        agent_name="crawl_web",
        session_key="test:c2",
    )

    tool = CheckSubagentsTool(mgr)
    tool.set_context("test", "c1", "test:c1")
    payload = json.loads(await tool.execute())

    assert payload["status"] == "ok"
    assert payload["running_count"] == 1
    assert {s["task_id"] for s in payload["subagents"]} == {"sub-1", "sub-2"}

    running_only = json.loads(await tool.execute(include_completed=False))
    assert [s["task_id"] for s in running_only["subagents"]] == ["sub-1"]

    running_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running_task


@pytest.mark.asyncio
async def test_check_subagents_reports_interrupted_snapshot(tmp_path):
    """Runtime snapshots should not map recoverable interruption to completed."""
    from secbot.agent.subagent import SubagentManager, SubagentStatus
    from secbot.agent.tools.subagents import CheckSubagentsTool
    from secbot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    )
    mgr._task_statuses["sub-interrupted"] = SubagentStatus(
        task_id="sub-interrupted",
        label="interrupted",
        task_description="budget exhausted",
        started_at=time.monotonic(),
        phase="done",
        stop_reason="context_exhausted",
        agent_name="vuln_scan",
        session_key="test:c1",
    )

    tool = CheckSubagentsTool(mgr)
    tool.set_context("test", "c1", "test:c1")
    payload = json.loads(await tool.execute())

    assert payload["subagents"][0]["state"] == "interrupted"
    assert payload["subagents"][0]["state"] != "completed"


@pytest.mark.asyncio
async def test_wait_for_subagents_timeout_does_not_cancel_running_task(tmp_path):
    """Manager wait timeouts must not cancel the underlying subagent."""
    from secbot.agent.subagent import SubagentManager, SubagentStatus
    from secbot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    )

    async def _hang_forever():
        await asyncio.Event().wait()

    running_task = asyncio.create_task(_hang_forever())
    mgr._running_tasks["sub-wait"] = running_task
    mgr._session_tasks.setdefault("test:c1", set()).add("sub-wait")
    mgr._task_statuses["sub-wait"] = SubagentStatus(
        task_id="sub-wait",
        label="waiting",
        task_description="long task",
        started_at=time.monotonic(),
        session_key="test:c1",
    )

    result = await mgr.wait_for_subagents(
        session_key="test:c1",
        task_id="sub-wait",
        timeout_sec=0.01,
    )

    assert result["status"] == "timeout"
    assert not running_task.done()

    running_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running_task


@pytest.mark.asyncio
async def test_wait_subagent_tool_returns_completed_snapshot(tmp_path):
    """wait_subagent should block until the selected subagent reaches terminal state."""
    from secbot.agent.subagent import SubagentManager, SubagentStatus
    from secbot.agent.tools.subagents import WaitSubagentTool
    from secbot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    )

    release = asyncio.Event()
    status = SubagentStatus(
        task_id="sub-complete",
        label="complete soon",
        task_description="short task",
        started_at=time.monotonic(),
        agent_name="crawl_web",
        session_key="test:c1",
    )

    async def _complete_after_release():
        await release.wait()
        status.phase = "done"
        status.stop_reason = "completed"

    running_task = asyncio.create_task(_complete_after_release())
    mgr._running_tasks["sub-complete"] = running_task
    mgr._session_tasks.setdefault("test:c1", set()).add("sub-complete")
    mgr._task_statuses["sub-complete"] = status

    tool = WaitSubagentTool(mgr)
    tool.set_context("test", "c1", "test:c1")
    wait_task = asyncio.create_task(
        tool.execute(task_id="sub-complete", timeout_sec=300)
    )

    await asyncio.sleep(0)
    release.set()
    payload = json.loads(await asyncio.wait_for(wait_task, timeout=2.0))

    assert payload["status"] == "completed"
    assert payload["completed_count"] == 1
    assert payload["subagents"][0]["task_id"] == "sub-complete"
    assert payload["subagents"][0]["state"] == "completed"


@pytest.mark.asyncio
async def test_wait_subagent_tool_returns_interrupted_for_budget_exhaustion(tmp_path):
    """wait_subagent aggregate status mirrors interrupted child status."""
    from secbot.agent.subagent import SubagentManager, SubagentStatus
    from secbot.agent.tools.subagents import WaitSubagentTool
    from secbot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    )

    release = asyncio.Event()
    status = SubagentStatus(
        task_id="sub-interrupt",
        label="interrupt soon",
        task_description="short task",
        started_at=time.monotonic(),
        agent_name="vuln_scan",
        session_key="test:c1",
    )

    async def _interrupt_after_release():
        await release.wait()
        status.phase = "done"
        status.stop_reason = "max_iterations"

    running_task = asyncio.create_task(_interrupt_after_release())
    mgr._running_tasks["sub-interrupt"] = running_task
    mgr._session_tasks.setdefault("test:c1", set()).add("sub-interrupt")
    mgr._task_statuses["sub-interrupt"] = status

    tool = WaitSubagentTool(mgr)
    tool.set_context("test", "c1", "test:c1")
    wait_task = asyncio.create_task(
        tool.execute(task_id="sub-interrupt", timeout_sec=300)
    )

    await asyncio.sleep(0)
    release.set()
    payload = json.loads(await asyncio.wait_for(wait_task, timeout=2.0))

    assert payload["status"] == "interrupted"
    assert payload["subagents"][0]["state"] == "interrupted"


@pytest.mark.asyncio
async def test_drain_pending_blocks_while_subagents_running(tmp_path):
    """_drain_pending should block when no messages are available but sub-agents are still running."""
    from secbot.agent.loop import AgentLoop
    from secbot.bus.events import InboundMessage
    from secbot.bus.queue import MessageBus
    from secbot.session.manager import Session

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")

    pending_queue: asyncio.Queue[InboundMessage] = asyncio.Queue()
    session = Session(key="test:drain-block")
    injection_callback = None

    # Capture the injection_callback that _run_agent_loop creates
    async def fake_runner_run(spec):
        nonlocal injection_callback
        injection_callback = spec.injection_callback

        # Simulate: first call to injection_callback should block because
        # sub-agents are running and no messages are in the queue yet.
        # We'll resolve this from a concurrent task.
        return SimpleNamespace(
            stop_reason="done",
            final_content="done",
            error=None,
            tool_events=[],
            messages=[],
            usage={},
            had_injections=False,
            tools_used=[],
        )

    loop.runner.run = AsyncMock(side_effect=fake_runner_run)

    # Register a running sub-agent in the SubagentManager for this session
    async def _hang_forever():
        await asyncio.Event().wait()

    hang_task = asyncio.create_task(_hang_forever())
    loop.subagents._session_tasks.setdefault(session.key, set()).add("sub-drain-1")
    loop.subagents._running_tasks["sub-drain-1"] = hang_task

    # Run _run_agent_loop — this defines the _drain_pending closure
    await loop._run_agent_loop(
        [{"role": "user", "content": "test"}],
        session=session,
        channel="test",
        chat_id="c1",
        pending_queue=pending_queue,
    )

    assert injection_callback is not None

    # Now test the callback directly
    # With sub-agents running and an empty queue, it should block
    drain_task = asyncio.create_task(injection_callback())

    # Give it a moment to enter the blocking wait
    await asyncio.sleep(0.05)

    # Should still be running (blocked on pending_queue.get())
    assert not drain_task.done(), "drain should block while sub-agents are running"

    # Now put a message in the queue (simulating sub-agent completion)
    await pending_queue.put(InboundMessage(
        sender_id="subagent",
        channel="test",
        chat_id="c1",
        content="Sub-agent result",
        media=None,
        metadata={},
    ))

    # Should unblock and return results
    results = await asyncio.wait_for(drain_task, timeout=2.0)
    assert len(results) >= 1
    assert results[0]["role"] == "user"
    assert "Sub-agent result" in str(results[0]["content"])

    # Cleanup
    hang_task.cancel()
    try:
        await hang_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_subagent_result_directly_wakes_active_parent_turn(tmp_path):
    """Subagent completion should not depend on the run-loop bus relay."""
    from secbot.agent.loop import AgentLoop
    from secbot.bus.queue import MessageBus
    from secbot.session.manager import Session

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")

    pending_queue: asyncio.Queue = asyncio.Queue()
    session = Session(key="test:parent")
    injection_callback = None

    async def fake_runner_run(spec):
        nonlocal injection_callback
        injection_callback = spec.injection_callback
        return SimpleNamespace(
            stop_reason="done",
            final_content="done",
            error=None,
            tool_events=[],
            messages=[],
            usage={},
            had_injections=False,
            tools_used=[],
        )

    loop.runner.run = AsyncMock(side_effect=fake_runner_run)

    await loop._run_agent_loop(
        [{"role": "user", "content": "test"}],
        session=session,
        channel="test",
        chat_id="parent",
        pending_queue=pending_queue,
    )

    assert injection_callback is not None

    async def _hang_forever():
        await asyncio.Event().wait()

    hang_task = asyncio.create_task(_hang_forever())
    loop.subagents._session_tasks.setdefault(session.key, set()).add("sub-direct-1")
    loop.subagents._running_tasks["sub-direct-1"] = hang_task
    loop._pending_queues[session.key] = pending_queue

    drain_task = asyncio.create_task(injection_callback())
    await asyncio.sleep(0.05)
    assert not drain_task.done()

    await loop.subagents._announce_result(
        "sub-direct-1",
        "vuln_detec",
        "scan target",
        "scan complete",
        {"channel": "test", "chat_id": "parent", "session_key": session.key},
        "ok",
        agent_name="vuln_detec",
    )

    results = await asyncio.wait_for(drain_task, timeout=2.0)
    assert len(results) == 1
    assert results[0]["role"] == "user"
    assert results[0]["injected_event"] == "subagent_result"
    assert results[0]["subagent_task_id"] == "sub-direct-1"
    assert "scan complete" in str(results[0]["content"])
    assert bus.inbound_size == 0

    hang_task.cancel()
    try:
        await hang_task
    except asyncio.CancelledError:
        pass
    loop._pending_queues.pop(session.key, None)


@pytest.mark.asyncio
async def test_drain_pending_no_block_when_no_subagents(tmp_path):
    """_drain_pending should not block when no sub-agents are running."""
    from secbot.agent.loop import AgentLoop
    from secbot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")

    pending_queue: asyncio.Queue = asyncio.Queue()
    injection_callback = None

    async def fake_runner_run(spec):
        nonlocal injection_callback
        injection_callback = spec.injection_callback
        return SimpleNamespace(
            stop_reason="done",
            final_content="done",
            error=None,
            tool_events=[],
            messages=[],
            usage={},
            had_injections=False,
            tools_used=[],
        )

    loop.runner.run = AsyncMock(side_effect=fake_runner_run)

    await loop._run_agent_loop(
        [{"role": "user", "content": "test"}],
        session=None,
        channel="test",
        chat_id="c1",
        pending_queue=pending_queue,
    )

    assert injection_callback is not None

    # With no sub-agents and empty queue, should return immediately
    results = await asyncio.wait_for(injection_callback(), timeout=1.0)
    assert results == []


@pytest.mark.asyncio
async def test_drain_pending_timeout(tmp_path):
    """_drain_pending should return empty after timeout when sub-agents hang."""
    from secbot.agent.loop import AgentLoop
    from secbot.bus.queue import MessageBus
    from secbot.session.manager import Session

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")

    pending_queue: asyncio.Queue = asyncio.Queue()
    session = Session(key="test:drain-timeout")
    injection_callback = None

    async def fake_runner_run(spec):
        nonlocal injection_callback
        injection_callback = spec.injection_callback
        return SimpleNamespace(
            stop_reason="done",
            final_content="done",
            error=None,
            tool_events=[],
            messages=[],
            usage={},
            had_injections=False,
            tools_used=[],
        )

    loop.runner.run = AsyncMock(side_effect=fake_runner_run)

    # Register a "running" sub-agent that will never complete
    async def _hang_forever():
        await asyncio.Event().wait()

    hang_task = asyncio.create_task(_hang_forever())
    loop.subagents._session_tasks.setdefault(session.key, set()).add("sub-timeout-1")
    loop.subagents._running_tasks["sub-timeout-1"] = hang_task

    await loop._run_agent_loop(
        [{"role": "user", "content": "test"}],
        session=session,
        channel="test",
        chat_id="c1",
        pending_queue=pending_queue,
    )

    assert injection_callback is not None

    # Patch the timeout to be very short for testing
    with patch("secbot.agent.loop.asyncio.wait_for") as mock_wait:
        mock_wait.side_effect = asyncio.TimeoutError
        results = await injection_callback()
        assert results == []

    # Cleanup
    hang_task.cancel()
    try:
        await hang_task
    except asyncio.CancelledError:
        pass


# ---------------------------------------------------------------------------
# PR3: SpawnTool(agent=) + scoped-skill filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_spawn_tool_rejects_unknown_agent(tmp_path):
    """create_agent(name='ghost') must error before hitting the manager."""
    from secbot.agent.subagent import SubagentManager
    from secbot.agent.tools.spawn import SpawnTool
    from secbot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        agent_registry=None,  # no registry attached
    )
    mgr.spawn = AsyncMock(return_value="should-not-be-called")

    tool = SpawnTool(mgr)
    tool.set_context("test", "c1", "test:c1")
    out = await tool.execute(name="ghost", task="hello", target="10.0.0.1")
    assert "create_agent failed" in out
    assert "no agent registry is attached" in out or "unknown agent 'ghost'" in out
    mgr.spawn.assert_not_called()


@pytest.mark.asyncio
async def test_spawn_tool_requires_target(tmp_path):
    """create_agent without 'target' must fail-fast (decision D6)."""
    from secbot.agent.subagent import SubagentManager
    from secbot.agent.tools.spawn import SpawnTool
    from secbot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    )
    mgr.spawn = AsyncMock(return_value="should-not-be-called")

    tool = SpawnTool(mgr)
    tool.set_context("test", "c1", "test:c1")
    out = await tool.execute(name="asset_discovery", task="enumerate")
    assert "create_agent failed" in out and "'target' is required" in out
    mgr.spawn.assert_not_called()


@pytest.mark.asyncio
async def test_spawn_tool_rejects_oversized_task(tmp_path):
    """create_agent must reject 'task' beyond MAX_TASK_LEN (decision D6)."""
    from secbot.agent.subagent import SubagentManager
    from secbot.agent.tools.spawn import MAX_TASK_LEN, SpawnTool
    from secbot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    )
    mgr.spawn = AsyncMock(return_value="should-not-be-called")

    tool = SpawnTool(mgr)
    tool.set_context("test", "c1", "test:c1")
    out = await tool.execute(
        name="asset_discovery",
        task="x" * (MAX_TASK_LEN + 1),
        target="10.0.0.1",
    )
    assert "exceeds the maximum" in out
    mgr.spawn.assert_not_called()


@pytest.mark.asyncio
async def test_spawn_tool_rejects_offline_agent(tmp_path, monkeypatch):
    """SpawnTool must refuse offline agents with a user-readable error."""
    from pathlib import Path as _Path

    from secbot.agent.subagent import SubagentManager
    from secbot.agent.tools.spawn import SpawnTool
    from secbot.agents.registry import load_agent_registry
    from secbot.bus.queue import MessageBus

    monkeypatch.setattr("secbot.agents.registry.shutil.which", lambda _n: None)
    agents_dir = _Path(__file__).resolve().parents[3] / "secbot" / "agents"
    skills_dir = _Path(__file__).resolve().parents[3] / "secbot" / "skills"
    registry = load_agent_registry(
        agents_dir, skill_names=None, skills_root=skills_dir
    )

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        agent_registry=registry,
    )
    mgr.spawn = AsyncMock(return_value="should-not-be-called")

    tool = SpawnTool(mgr)
    tool.set_context("test", "c1", "test:c1")
    out = await tool.execute(name="asset_discovery", task="scan", target="10.0.0.0/24")
    assert "offline" in out
    assert "missing binaries" in out
    mgr.spawn.assert_not_called()


@pytest.mark.asyncio
async def test_spawn_tool_endpoint_bound_requires_endpoint_fields(tmp_path, monkeypatch):
    """Endpoint-bound experts MUST receive endpoint_url + endpoint_param (D6/D8)."""
    from pathlib import Path as _Path

    from secbot.agent.subagent import SubagentManager
    from secbot.agent.tools.spawn import SpawnTool
    from secbot.agents.registry import load_agent_registry
    from secbot.bus.queue import MessageBus

    # All binaries considered present so we exercise the endpoint check, not
    # the offline-agent check.
    monkeypatch.setattr("secbot.agents.registry.shutil.which", lambda _n: "/usr/bin/true")
    agents_dir = _Path(__file__).resolve().parents[3] / "secbot" / "agents"
    skills_dir = _Path(__file__).resolve().parents[3] / "secbot" / "skills"
    registry = load_agent_registry(
        agents_dir, skill_names=None, skills_root=skills_dir
    )

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        agent_registry=registry,
    )
    mgr.spawn = AsyncMock(return_value="should-not-be-called")

    tool = SpawnTool(mgr)
    tool.set_context("test", "c1", "test:c1")
    out = await tool.execute(
        name="vuln_detec",
        task="probe",
        target="https://example.com/login",
    )
    assert "endpoint-bound" in out and "'endpoint_url' is required" in out
    mgr.spawn.assert_not_called()


@pytest.mark.asyncio
async def test_subagent_manager_endpoint_mutex(tmp_path):
    """A second endpoint-bound spawn against the same endpoint must be rejected (D5)."""
    from secbot.agent.subagent import SubagentManager
    from secbot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    )
    # Stub the heavy bg task so the bookkeeping is exercised in isolation.
    mgr._run_subagent = AsyncMock(return_value=None)

    first = await mgr.spawn(
        task="t1",
        agent=None,  # no registry needed for the manager-level mutex check
        endpoint_url="HTTPS://Example.com:443/login/",
        endpoint_param="username",
    )
    assert "started" in first

    second = await mgr.spawn(
        task="t2",
        agent=None,
        # Same endpoint, just spelled differently — normalisation must collapse.
        endpoint_url="https://example.com/login",
        endpoint_param="USERNAME",
    )
    assert "endpoint already busy" in second


@pytest.mark.asyncio
async def test_subagent_registers_only_scoped_skills(tmp_path):
    """_run_subagent must filter skill tools to spec.scoped_skills."""
    from pathlib import Path as _Path

    from secbot.agent.subagent import SubagentManager, SubagentStatus
    from secbot.agents.registry import load_agent_registry
    from secbot.bus.queue import MessageBus

    agents_dir = _Path(__file__).resolve().parents[3] / "secbot" / "agents"
    registry = load_agent_registry(agents_dir, skill_names=None)
    spec = registry.get("crawl_web")

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        agent_registry=registry,
    )
    mgr._announce_result = AsyncMock()

    captured: dict = {}

    async def fake_run(run_spec):
        captured["tool_names"] = set(run_spec.tools.tool_names)
        captured["initial_messages"] = run_spec.initial_messages
        captured["system_prompt"] = run_spec.initial_messages[0]["content"]
        captured["user_message"] = run_spec.initial_messages[1]["content"]
        return SimpleNamespace(
            stop_reason="done", final_content="done", error=None, tool_events=[]
        )

    mgr.runner.run = AsyncMock(side_effect=fake_run)

    status = SubagentStatus(
        task_id="sub-x",
        label="label",
        task_description="scan",
        started_at=time.monotonic(),
    )
    await mgr._run_subagent(
        "sub-x",
        "scan targets",
        "label",
        {"channel": "test", "chat_id": "c1"},
        status,
        None,
        spec,
    )

    # Only crawl_web's scoped skill must appear; others are excluded. The
    # orchestrator-only ``create_agent`` tool MUST NOT be available either.
    assert "create_agent" not in captured["tool_names"]
    assert "delegate_task" not in captured["tool_names"]
    assert "blackboard_write" in captured["tool_names"]
    assert "read_blackboard" in captured["tool_names"]
    for skill in spec.scoped_skills:
        assert skill in captured["tool_names"], f"missing {skill}"
    assert "katana-crawl-web" in captured["tool_names"]
    for skill in ("qscan-host-discovery", "nuclei-template-scan", "hydra-bruteforce"):
        assert skill not in captured["tool_names"], f"{skill} must be scoped out"

    # The system prompt is only the slim scaffold. Per-agent instructions are
    # composed into the user message so expert execution rules are not lost.
    assert [msg["role"] for msg in captured["initial_messages"]] == ["system", "user"]
    sys_prompt = captured["system_prompt"]
    spec_first_line = spec.system_prompt.strip().split("\n", 1)[0]
    if spec_first_line and len(spec_first_line) > 8:
        assert spec_first_line not in sys_prompt
    assert "Do not reconstruct Katana output paths" not in sys_prompt
    assert "raw_urls_path" not in sys_prompt
    user_message = captured["user_message"]
    assert user_message.startswith("# Expert Execution Contract\n\n")
    assert spec_first_line in user_message
    assert "Do not reconstruct Katana output paths" in user_message
    assert "raw_urls_path" in user_message
    assert user_message.endswith("# Orchestrator Task\n\nscan targets")


# ---------------------------------------------------------------------------
# minimal_tools: restrict tool surface to scoped SkillTools only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subagent_minimal_tools_only_scoped_skills(tmp_path):
    """minimal_tools=True agents must receive ONLY their scoped SkillTools.

    No file tools, curl, blackboard, ask_user, exec, or asset_feed may be
    registered.  This prevents agents like ``report`` from wandering into
    unrelated tools (e.g. curl→sqlite3).
    """
    from secbot.agent.subagent import SubagentManager, SubagentStatus
    from secbot.agents.registry import ExpertAgentSpec
    from secbot.bus.queue import MessageBus
    from secbot.config.schema import ExecToolConfig

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        exec_config=ExecToolConfig(enable=True),
    )
    mgr._announce_result = AsyncMock()

    # Use report-html as the scoped skill (it has no external binary so it
    # always loads successfully).
    spec = ExpertAgentSpec(
        name="report",
        display_name="Report",
        description="test",
        system_prompt="test",
        scoped_skills=("report-html",),
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        minimal_tools=True,
    )

    captured: dict = {}

    async def fake_run(run_spec):
        captured["tool_names"] = set(run_spec.tools.tool_names)
        return SimpleNamespace(
            stop_reason="done",
            final_content="done",
            error=None,
            tool_events=[],
        )

    mgr.runner.run = AsyncMock(side_effect=fake_run)

    status = SubagentStatus(
        task_id="sub-1", label="label", task_description="do task", started_at=time.monotonic()
    )
    await mgr._run_subagent(
        "sub-1", "do task", "label", {"channel": "test", "chat_id": "c1"}, status, None, spec
    )

    mgr.runner.run.assert_awaited_once()

    tool_names = captured["tool_names"]

    # The ONLY registered tool must be the scoped skill.
    assert "report-html" in tool_names, "scoped skill 'report-html' must be present"

    # Non-skill tools must be absent.
    for blocked in (
        "read_file", "write_file", "edit_file", "list_dir",
        "glob", "grep", "ask_user",
        "blackboard_write", "read_blackboard",
        "curl", "exec",
        "asset_push", "read_assets",
    ):
        assert blocked not in tool_names, f"'{blocked}' must NOT be registered for minimal_tools agent"


@pytest.mark.asyncio
async def test_subagent_non_minimal_still_gets_full_tools(tmp_path):
    """minimal_tools=False (default) agents must receive the full tool set."""
    from secbot.agent.subagent import SubagentManager, SubagentStatus
    from secbot.agents.registry import ExpertAgentSpec
    from secbot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    )
    mgr._announce_result = AsyncMock()

    spec = ExpertAgentSpec(
        name="crawl_web",
        display_name="Crawl Web",
        description="test",
        system_prompt="test",
        scoped_skills=("katana-crawl-web",),
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        # minimal_tools defaults to False
    )

    captured: dict = {}

    async def fake_run(run_spec):
        captured["tool_names"] = set(run_spec.tools.tool_names)
        return SimpleNamespace(
            stop_reason="done",
            final_content="done",
            error=None,
            tool_events=[],
        )

    mgr.runner.run = AsyncMock(side_effect=fake_run)

    status = SubagentStatus(
        task_id="sub-2", label="label", task_description="do task", started_at=time.monotonic()
    )
    await mgr._run_subagent(
        "sub-2", "do task", "label", {"channel": "test", "chat_id": "c1"}, status, None, spec
    )

    mgr.runner.run.assert_awaited_once()

    tool_names = captured["tool_names"]

    # Standard non-skill tools must be present.
    for expected in ("read_file", "write_file", "curl", "blackboard_write", "read_blackboard"):
        assert expected in tool_names, f"'{expected}' must be registered for non-minimal agent"
    # Scoped skill must also be present.
    assert "katana-crawl-web" in tool_names

"""Tests for subagent tool registration and wiring."""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from secbot.config.schema import AgentDefaults

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars


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
        scoped_skills=("nmap-port-scan",),
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
    result = await tool.execute(task="first task")
    assert "started" in result

    # Second spawn should be rejected (default limit is 1)
    result = await tool.execute(task="second task")
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
    """SpawnTool(agent=\"missing\") must error before hitting the manager."""
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
    out = await tool.execute(task="hello", agent="ghost")
    assert "Unknown expert agent 'ghost'" in out
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
    out = await tool.execute(task="scan", agent="asset_discovery")
    assert "offline" in out
    assert "missing binaries" in out
    mgr.spawn.assert_not_called()


@pytest.mark.asyncio
async def test_subagent_registers_only_scoped_skills(tmp_path):
    """_run_subagent must filter skill tools to spec.scoped_skills."""
    from pathlib import Path as _Path

    from secbot.agent.subagent import SubagentManager, SubagentStatus
    from secbot.agents.registry import load_agent_registry
    from secbot.bus.queue import MessageBus

    agents_dir = _Path(__file__).resolve().parents[3] / "secbot" / "agents"
    registry = load_agent_registry(agents_dir, skill_names=None)
    spec = registry.get("port_scan")

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
        captured["system_prompt"] = run_spec.initial_messages[0]["content"]
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

    # Only port_scan's 3 scoped skills must appear; others are excluded.
    assert "delegate_task" not in captured["tool_names"]
    assert "blackboard_write" in captured["tool_names"]
    assert "read_blackboard" in captured["tool_names"]
    for skill in spec.scoped_skills:
        assert skill in captured["tool_names"], f"missing {skill}"
    for skill in ("nmap-host-discovery", "nuclei-template-scan", "hydra-bruteforce"):
        assert skill not in captured["tool_names"], f"{skill} must be scoped out"

    # Spec system_prompt must be prepended to the subagent system message.
    assert spec.system_prompt.strip().split("\n", 1)[0] in captured["system_prompt"]


@pytest.mark.asyncio
async def test_subagent_injects_blackboard_into_system_prompt(tmp_path):
    """_run_subagent must inject current blackboard entries into the system prompt."""
    from secbot.agent.blackboard import BlackboardRegistry
    from secbot.agent.subagent import SubagentManager, SubagentStatus
    from secbot.bus.queue import MessageBus

    registry = BlackboardRegistry()
    board = await registry.get_or_create("chat-1")
    await board.write("asset_discovery", "[finding] 80,443 open on 10.0.0.1")
    await board.write("port_scan", "[milestone] sweep complete")

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        blackboard_registry=registry,
    )
    mgr._announce_result = AsyncMock()

    captured: dict = {}

    async def fake_run(run_spec):
        captured["system_prompt"] = run_spec.initial_messages[0]["content"]
        return SimpleNamespace(
            stop_reason="done", final_content="done", error=None, tool_events=[]
        )

    mgr.runner.run = AsyncMock(side_effect=fake_run)

    status = SubagentStatus(
        task_id="sub-y",
        label="label",
        task_description="scan",
        started_at=time.monotonic(),
    )
    await mgr._run_subagent(
        "sub-y",
        "scan targets",
        "label",
        {"channel": "test", "chat_id": "chat-1"},
        status,
    )

    prompt = captured["system_prompt"]
    assert "Shared Blackboard (findings from previous agents)" in prompt
    assert "[asset_discovery]" in prompt
    assert "[finding] 80,443 open on 10.0.0.1" in prompt
    assert "[port_scan]" in prompt
    assert "[milestone] sweep complete" in prompt


@pytest.mark.asyncio
async def test_subagent_injects_empty_blackboard_placeholder(tmp_path):
    """When the blackboard is empty, a placeholder should still be injected."""
    from secbot.agent.blackboard import BlackboardRegistry
    from secbot.agent.subagent import SubagentManager, SubagentStatus
    from secbot.bus.queue import MessageBus

    registry = BlackboardRegistry()
    # Do NOT write anything — board stays empty.
    _ = await registry.get_or_create("chat-2")

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        blackboard_registry=registry,
    )
    mgr._announce_result = AsyncMock()

    captured: dict = {}

    async def fake_run(run_spec):
        captured["system_prompt"] = run_spec.initial_messages[0]["content"]
        return SimpleNamespace(
            stop_reason="done", final_content="done", error=None, tool_events=[]
        )

    mgr.runner.run = AsyncMock(side_effect=fake_run)

    status = SubagentStatus(
        task_id="sub-z",
        label="label",
        task_description="scan",
        started_at=time.monotonic(),
    )
    await mgr._run_subagent(
        "sub-z",
        "scan targets",
        "label",
        {"channel": "test", "chat_id": "chat-2"},
        status,
    )

    prompt = captured["system_prompt"]
    assert "Shared Blackboard" in prompt
    assert "currently empty" in prompt

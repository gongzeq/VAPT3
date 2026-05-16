"""Tests for persistent teammate communication."""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from secbot.agent.teammate import (
    TEAM_STATUS_IDLE,
    TEAM_STATUS_SHUTDOWN,
    TEAM_STATUS_WORKING,
    TeamConfigStore,
    TeammateManager,
    TeamMessageBus,
)
from secbot.agent.tools.teammate import (
    ReadTeammateInboxTool,
    SendTeammateMessageTool,
    ShutdownTeammateTool,
    SpawnTeammateTool,
)
from secbot.config.schema import AgentDefaults

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars


def _provider() -> MagicMock:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    return provider


@pytest.mark.asyncio
async def test_mailbox_send_appends_jsonl_and_read_drains(tmp_path):
    bus = TeamMessageBus(tmp_path)

    await bus.send(sender="orchestrator", to="alice", content="hello", msg_type="request")
    await bus.send(sender="bob", to="alice", content="second")

    path = tmp_path / ".team" / "inbox" / "alice.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["content"] for row in rows] == ["hello", "second"]
    assert rows[0]["type"] == "request"
    assert rows[0]["from"] == "orchestrator"

    drained = await bus.read_inbox("alice")
    assert [msg["content"] for msg in drained] == ["hello", "second"]
    assert path.read_text(encoding="utf-8") == ""
    assert await bus.read_inbox("alice") == []


def test_team_config_persists_identity_role_and_status(tmp_path):
    store = TeamConfigStore(tmp_path)
    store.upsert(
        name="Alice",
        role="reviewer",
        status=TEAM_STATUS_WORKING,
        current_task="inspect",
    )

    reloaded = TeamConfigStore(tmp_path)
    record = reloaded.get("alice")

    assert record is not None
    assert record.name == "alice"
    assert record.role == "reviewer"
    assert record.status == TEAM_STATUS_WORKING
    assert record.current_task == "inspect"
    assert (tmp_path / ".team" / "config.json").exists()


def test_teammate_manager_reconciles_stale_working_records(tmp_path):
    store = TeamConfigStore(tmp_path)
    store.upsert(
        name="alice",
        role="analyst",
        status=TEAM_STATUS_WORKING,
        current_task="interrupted task",
    )

    TeammateManager(
        provider=_provider(),
        workspace=tmp_path,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    )

    recovered = TeamConfigStore(tmp_path).get("alice")
    assert recovered is not None
    assert recovered.status == TEAM_STATUS_IDLE
    assert recovered.current_task is None
    assert recovered.last_error == "Recovered from interrupted teammate run."


@pytest.mark.asyncio
async def test_teammate_lifecycle_spawn_work_idle_work_shutdown(tmp_path):
    mgr = TeammateManager(
        provider=_provider(),
        workspace=tmp_path,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    )
    calls: list[str] = []

    async def fake_run(spec):
        assert threading.current_thread().name == "secbot-teammate-alice"
        calls.append(spec.initial_messages[-1]["content"])
        assert spec.session_key == "teammate:alice"
        assert {"list_teammates", "send_teammate_message", "read_teammate_inbox"} <= set(
            spec.tools.tool_names
        )
        return SimpleNamespace(
            stop_reason="completed",
            final_content=f"done {len(calls)}",
            error=None,
            tool_events=[],
            messages=spec.initial_messages + [{"role": "assistant", "content": "done"}],
            tools_used=[],
            usage={},
            had_injections=False,
        )

    mgr.runner.run = AsyncMock(side_effect=fake_run)

    first = await mgr.spawn(name="alice", role="analyst", task="first task")
    assert first.status == TEAM_STATUS_WORKING
    first_idle = await mgr.wait_for_idle("alice")
    assert first_idle.status == TEAM_STATUS_IDLE
    assert first_idle.last_result == "done 1"

    second = await mgr.spawn(name="alice", role="analyst", task="second task")
    assert second.status == TEAM_STATUS_WORKING
    second_idle = await mgr.wait_for_idle("alice")
    assert second_idle.status == TEAM_STATUS_IDLE
    assert second_idle.last_result == "done 2"
    assert calls == ["first task", "second task"]

    shutdown = await mgr.shutdown("alice")
    assert shutdown.status == TEAM_STATUS_SHUTDOWN

    with pytest.raises(RuntimeError, match="shutdown"):
        await mgr.spawn(name="alice", role="analyst", task="third task")


@pytest.mark.asyncio
async def test_teammate_tools_cover_manual_surface(tmp_path):
    mgr = TeammateManager(
        provider=_provider(),
        workspace=tmp_path,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    )

    async def fake_run(_spec):
        return SimpleNamespace(
            stop_reason="completed",
            final_content="done",
            error=None,
            tool_events=[],
            messages=[],
            tools_used=[],
            usage={},
            had_injections=False,
        )

    mgr.runner.run = AsyncMock(side_effect=fake_run)

    spawn_result = await SpawnTeammateTool(mgr).execute(
        name="alice",
        role="analyst",
        task="work",
    )
    assert "alice" in spawn_result
    await mgr.wait_for_idle("alice")

    send_result = await SendTeammateMessageTool(mgr).execute(
        to="alice",
        content="check inbox",
    )
    assert "Message sent" in send_result

    inbox_result = await ReadTeammateInboxTool(mgr).execute(name="alice")
    assert "check inbox" in inbox_result
    assert await ReadTeammateInboxTool(mgr).execute(name="alice") == "Inbox is empty."

    shutdown_result = await ShutdownTeammateTool(mgr).execute(name="alice")
    assert "shutdown" in shutdown_result

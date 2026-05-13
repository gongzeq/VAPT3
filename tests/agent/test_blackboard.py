"""Tests for Blackboard module."""

from __future__ import annotations

import asyncio

import pytest

from secbot.agent.blackboard import Blackboard, BlackboardEntry, BlackboardRegistry
from secbot.agent.tools.blackboard import BlackboardReadTool, BlackboardWriteTool


@pytest.mark.asyncio
async def test_write_and_read():
    """Basic write and read."""
    bb = Blackboard()
    entry = await bb.write("agent_a", "Found open port 80")
    assert isinstance(entry, BlackboardEntry)
    assert entry.agent_name == "agent_a"
    assert entry.text == "Found open port 80"
    assert entry.id  # non-empty

    entries = await bb.read_all()
    assert len(entries) == 1
    assert entries[0].text == "Found open port 80"


@pytest.mark.asyncio
async def test_multiple_writes():
    """Multiple agents writing."""
    bb = Blackboard()
    await bb.write("agent_a", "Finding 1")
    await bb.write("agent_b", "Finding 2")
    await bb.write("agent_a", "Finding 3")

    entries = await bb.read_all()
    assert len(entries) == 3
    assert entries[0].agent_name == "agent_a"
    assert entries[1].agent_name == "agent_b"
    assert entries[2].agent_name == "agent_a"


@pytest.mark.asyncio
async def test_concurrent_writes():
    """Concurrent writes should be safe."""
    bb = Blackboard()

    async def writer(name: str, count: int):
        for i in range(count):
            await bb.write(name, f"entry-{i}")

    await asyncio.gather(
        writer("a", 50),
        writer("b", 50),
        writer("c", 50),
    )

    entries = await bb.read_all()
    assert len(entries) == 150


@pytest.mark.asyncio
async def test_clear():
    """Clear should remove all entries."""
    bb = Blackboard()
    await bb.write("agent_a", "something")
    assert len(bb) == 1

    await bb.clear()
    assert len(bb) == 0
    entries = await bb.read_all()
    assert entries == []


@pytest.mark.asyncio
async def test_read_returns_copy():
    """read_all returns a copy, modifications don't affect internal state."""
    bb = Blackboard()
    await bb.write("agent_a", "entry1")
    entries = await bb.read_all()
    entries.clear()
    assert len(bb) == 1  # internal not affected


@pytest.mark.asyncio
async def test_to_dict_list():
    """Serialization to dict list."""
    bb = Blackboard()
    await bb.write("agent_a", "finding")
    dicts = await bb.to_dict_list()
    assert len(dicts) == 1
    assert dicts[0]["agent_name"] == "agent_a"
    assert dicts[0]["text"] == "finding"
    assert "id" in dicts[0]
    assert "timestamp" in dicts[0]


@pytest.mark.asyncio
async def test_write_tool():
    """BlackboardWriteTool basic usage."""
    bb = Blackboard()
    tool = BlackboardWriteTool(bb, agent_name="scanner")
    result = await tool.execute(text="Found vulnerability CVE-2024-1234")
    assert "Written to blackboard" in result
    assert len(bb) == 1


@pytest.mark.asyncio
async def test_write_tool_empty_text():
    """BlackboardWriteTool rejects empty text."""
    bb = Blackboard()
    tool = BlackboardWriteTool(bb, agent_name="scanner")
    result = await tool.execute(text="   ")
    assert "Error" in result
    assert len(bb) == 0


@pytest.mark.asyncio
async def test_read_tool_empty():
    """BlackboardReadTool on empty blackboard."""
    bb = Blackboard()
    tool = BlackboardReadTool(bb)
    assert tool.name == "read_blackboard"
    result = await tool.execute()
    assert "empty" in result.lower()


@pytest.mark.asyncio
async def test_read_tool_with_entries():
    """BlackboardReadTool with entries."""
    bb = Blackboard()
    await bb.write("agent_a", "Port 22 open")
    await bb.write("agent_b", "SSH vulnerable")
    tool = BlackboardReadTool(bb)
    result = await tool.execute()
    assert "agent_a" in result
    assert "agent_b" in result
    assert "Port 22 open" in result
    assert "SSH vulnerable" in result


# ---------------------------------------------------------------------------
# Kind auto-extraction (P0/B3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text,expected",
    [
        ("[milestone] Done with discovery", "milestone"),
        ("[blocker] Stuck on creds", "blocker"),
        ("[finding] Port 22 open", "finding"),
        ("[progress] 30% scanned", "progress"),
        # Leading whitespace + case-insensitive matching.
        ("   [Milestone] mixed case", "milestone"),
        ("\t[BLOCKER] tab prefix", "blocker"),
    ],
)
async def test_write_extracts_known_kind(text: str, expected: str) -> None:
    bb = Blackboard()
    entry = await bb.write("agent_a", text)
    assert entry.kind == expected
    # to_dict must transparently surface the kind.
    assert entry.to_dict()["kind"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "no prefix at all",
        "[unknown] not in known set",
        "milestone] missing leading bracket",
        "[milestone something",  # missing closing bracket
        "",
    ],
)
async def test_write_kind_falls_back_to_none(text: str) -> None:
    bb = Blackboard()
    entry = await bb.write("agent_a", text)
    assert entry.kind is None
    assert entry.to_dict()["kind"] is None


@pytest.mark.asyncio
async def test_to_dict_list_preserves_kind() -> None:
    bb = Blackboard()
    await bb.write("agent_a", "[finding] open port 80")
    await bb.write("agent_b", "no prefix here")
    payload = await bb.to_dict_list()
    assert [row["kind"] for row in payload] == ["finding", None]


# ---------------------------------------------------------------------------
# BlackboardRegistry — per-chat isolation (P0/D3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registry_isolates_boards_per_chat_id() -> None:
    registry = BlackboardRegistry()
    board_a = await registry.get_or_create("chat-a")
    board_b = await registry.get_or_create("chat-b")
    assert board_a is not board_b

    await board_a.write("agent", "[milestone] for chat-a")
    await board_b.write("agent", "[finding] for chat-b")

    assert len(board_a) == 1
    assert len(board_b) == 1


@pytest.mark.asyncio
async def test_registry_get_or_create_returns_same_instance() -> None:
    registry = BlackboardRegistry()
    first = await registry.get_or_create("chat-x")
    second = await registry.get_or_create("chat-x")
    assert first is second


@pytest.mark.asyncio
async def test_registry_get_returns_none_for_unknown_chat() -> None:
    registry = BlackboardRegistry()
    assert await registry.get("never-created") is None
    assert "never-created" not in registry.chat_ids()


@pytest.mark.asyncio
async def test_registry_drop_removes_board() -> None:
    registry = BlackboardRegistry()
    await registry.get_or_create("chat-y")
    assert "chat-y" in registry.chat_ids()
    await registry.drop("chat-y")
    assert "chat-y" not in registry.chat_ids()
    assert await registry.get("chat-y") is None


@pytest.mark.asyncio
async def test_registry_concurrent_get_or_create_is_singleton() -> None:
    registry = BlackboardRegistry()
    boards = await asyncio.gather(
        *[registry.get_or_create("chat-z") for _ in range(20)]
    )
    first = boards[0]
    assert all(b is first for b in boards)

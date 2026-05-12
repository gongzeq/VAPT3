"""Tests for Blackboard module."""

from __future__ import annotations

import asyncio

import pytest

from secbot.agent.blackboard import Blackboard, BlackboardEntry
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

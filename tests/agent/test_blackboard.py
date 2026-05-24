"""Tests for Blackboard module."""

from __future__ import annotations

import asyncio

import pytest

from secbot.agent.blackboard import (
    Blackboard,
    BlackboardEntry,
    BlackboardRegistry,
    BlackboardValueError,
)
from secbot.agent.tools.blackboard import (
    BlackboardReadFullTool,
    BlackboardReadTool,
    BlackboardWriteTool,
)
from secbot.agent.tools.registry import ToolRegistry
from secbot.policy import PolicyContext


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
    assert dicts[0]["payload"] == {"text": "finding"}


@pytest.mark.asyncio
async def test_write_tool():
    """BlackboardWriteTool basic usage."""
    bb = Blackboard()
    tool = BlackboardWriteTool(bb, agent_name="scanner")
    result = await tool.execute(text="Found vulnerability CVE-2024-1234")
    assert "Written to blackboard" in result
    assert len(bb) == 1


@pytest.mark.asyncio
async def test_write_tool_structured_payload() -> None:
    bb = Blackboard()
    tool = BlackboardWriteTool(bb, agent_name="scanner")

    result = await tool.execute(
        kind="hypothesis",
        payload={"title": "possible SSRF", "kind": "ssrf", "confidence": 0.7},
    )

    assert "kind=hypothesis" in result
    [entry] = await bb.read_by_kind(["hypothesis"])
    assert entry.payload == {"title": "possible SSRF", "kind": "ssrf", "confidence": 0.7}


@pytest.mark.asyncio
async def test_write_tool_structured_validation_error() -> None:
    bb = Blackboard()
    tool = BlackboardWriteTool(bb, agent_name="scanner")

    result = await tool.execute(kind="hypothesis", payload={"title": "missing fields"})

    assert result.startswith("Error:")
    assert len(bb) == 0


@pytest.mark.asyncio
async def test_worker_write_finding_denied_by_tool_router() -> None:
    bb = Blackboard()
    registry = ToolRegistry(
        policy_context=PolicyContext(caller_kind="worker", worker_id="worker-1")
    )
    registry.register(BlackboardWriteTool(bb, agent_name="worker"))

    result = await registry.execute(
        "blackboard_write",
        {
            "kind": "finding",
            "payload": {
                "title": "must be promoted by pi",
                "severity": "high",
                "cwe": "CWE-79",
                "owasp_category": "A03",
                "asset_ref": "web",
                "evidence_ids": [],
            },
        },
    )

    assert "policy_denied" in result
    assert "caller_kind" in result
    assert len(bb) == 0


@pytest.mark.asyncio
async def test_worker_write_hypothesis_allowed_by_tool_router() -> None:
    bb = Blackboard()
    registry = ToolRegistry(
        policy_context=PolicyContext(caller_kind="worker", worker_id="worker-1")
    )
    registry.register(BlackboardWriteTool(bb, agent_name="worker"))

    result = await registry.execute(
        "blackboard_write",
        {
            "kind": "hypothesis",
            "payload": {"title": "possible SSRF", "kind": "ssrf", "confidence": 0.7},
        },
    )

    assert "kind=hypothesis" in result
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
    await bb.write("agent_a", "[milestone] mapping complete")
    await bb.write(
        "agent_b",
        "finding",
        {
            "title": "SSH weak cipher",
            "severity": "medium",
            "cwe": "CWE-327",
            "owasp_category": "A02",
            "asset_ref": "host:22",
            "evidence_ids": ["ev1"],
        },
    )
    tool = BlackboardReadTool(bb)
    result = await tool.execute()
    assert "Blackboard Snapshot" in result
    assert "mapping complete" in result
    assert "SSH weak cipher" in result


@pytest.mark.asyncio
async def test_read_full_tool_filters_by_kind() -> None:
    bb = Blackboard()
    await bb.write("agent_a", "[milestone] mapping complete")
    await bb.write("agent_b", "[blocker] missing creds")
    tool = BlackboardReadFullTool(bb)

    result = await tool.execute(kinds=["blocker"])

    assert "missing creds" in result
    assert "mapping complete" not in result


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
    assert entry.payload
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
async def test_write_kind_falls_back_to_legacy_text(text: str) -> None:
    bb = Blackboard()
    entry = await bb.write("agent_a", text)
    assert entry.kind == "legacy_text"
    assert entry.payload == {"text": text}
    assert entry.to_dict()["kind"] == "legacy_text"


@pytest.mark.asyncio
async def test_to_dict_list_preserves_kind() -> None:
    bb = Blackboard()
    await bb.write("agent_a", "[finding] open port 80")
    await bb.write("agent_b", "no prefix here")
    payload = await bb.to_dict_list()
    assert [row["kind"] for row in payload] == ["finding", "legacy_text"]
    assert payload[0]["payload"]["title"] == "open port 80"
    assert payload[1]["payload"] == {"text": "no prefix here"}


# ---------------------------------------------------------------------------
# Structured blackboard (PR1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_structured_scope_entry() -> None:
    bb = Blackboard()

    entry = await bb.write(
        "pi",
        "scope",
        {
            "in_scope": ["https://example.test"],
            "out_of_scope": ["169.254.169.254"],
            "forbidden_actions": ["destructive"],
        },
    )

    assert entry.kind == "scope"
    assert entry.text is None
    assert entry.payload == {
        "in_scope": ["https://example.test"],
        "out_of_scope": ["169.254.169.254"],
        "forbidden_actions": ["destructive"],
    }
    assert entry.to_dict()["payload"]["in_scope"] == ["https://example.test"]


@pytest.mark.asyncio
async def test_write_structured_rejects_unknown_kind() -> None:
    bb = Blackboard()

    with pytest.raises(BlackboardValueError, match="unknown kind"):
        await bb.write("pi", "candidate_finding", {"title": "not a PR1 kind"})


@pytest.mark.asyncio
async def test_write_structured_rejects_missing_required_field() -> None:
    bb = Blackboard()

    with pytest.raises(BlackboardValueError, match="confidence"):
        await bb.write("worker", "hypothesis", {"title": "possible XSS", "kind": "input-validation"})


@pytest.mark.asyncio
async def test_read_by_kind_and_legacy_read_limit() -> None:
    bb = Blackboard()
    await bb.write("agent", "[milestone] first")
    await bb.write("agent", "[blocker] second")
    await bb.write("agent", "third")

    blockers = await bb.read_by_kind(["blocker"])
    assert [entry.text for entry in blockers] == ["[blocker] second"]
    legacy_entries = await bb.read_by_kind(["legacy_text"])
    assert [entry.text for entry in legacy_entries] == ["third"]

    tail = await bb.read(limit=2)
    assert [entry.text for entry in tail] == ["[blocker] second", "third"]


@pytest.mark.asyncio
async def test_snapshot_aggregates_and_sorts_findings() -> None:
    bb = Blackboard()
    await bb.write("pi", "scope", {"in_scope": ["a"], "out_of_scope": []})
    await bb.write(
        "pi",
        "phase_transition",
        {"from": "Intake", "to": "Safe Validation", "reason": "ready"},
    )
    await bb.write(
        "pi",
        "finding",
        {
            "title": "low issue",
            "severity": "low",
            "cwe": "CWE-200",
            "owasp_category": "A01",
            "asset_ref": "a",
            "evidence_ids": [],
        },
    )
    await bb.write(
        "pi",
        "finding",
        {
            "title": "critical issue",
            "severity": "critical",
            "cwe": "CWE-89",
            "owasp_category": "A03",
            "asset_ref": "a",
            "evidence_ids": ["ev1"],
        },
    )
    await bb.write(
        "worker",
        "hypothesis",
        {"title": "needs authz check", "kind": "authz", "confidence": 0.8},
    )
    await bb.write(
        "pi",
        "approval",
        {"action": "run intrusive validation", "requested_at": "now", "state": "pending"},
    )

    snapshot = await bb.snapshot()

    assert snapshot.current_phase == "Safe Validation"
    assert snapshot.scope == {"in_scope": ["a"], "out_of_scope": []}
    assert [finding["title"] for finding in snapshot.findings] == [
        "critical issue",
        "low issue",
    ]
    assert [hyp["title"] for hyp in snapshot.open_hypotheses] == ["needs authz check"]
    assert snapshot.pending_approvals[0]["action"] == "run intrusive validation"


@pytest.mark.asyncio
async def test_snapshot_truncates_findings() -> None:
    bb = Blackboard()
    for index in range(60):
        await bb.write(
            "pi",
            "finding",
            {
                "title": f"finding {index}",
                "severity": "info",
                "cwe": "CWE-200",
                "owasp_category": "A01",
                "asset_ref": "a",
                "evidence_ids": [],
            },
        )

    snapshot = await bb.snapshot()

    assert len(snapshot.findings) == 50
    assert snapshot.truncated_findings == 10


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


# ---------------------------------------------------------------------------
# Blackboard context injection for subagents — REMOVED (D3)
# The _format_blackboard_context helper was deleted because subagents no longer
# receive auto-injected blackboard snapshots. The Orchestrator is responsible
# for inlining any relevant context via the 'task' field.

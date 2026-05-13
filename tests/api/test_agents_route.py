"""Tests for ``GET /api/agents`` (P0/B1).

Spec: ``.trellis/spec/backend/agent-registry-contract.md`` and
``.trellis/spec/backend/dashboard-aggregation.md`` §2.6.

The default response shape MUST stay byte-stable when no
``include_status=true`` query is supplied. With the flag, the handler
enriches each entry from the injected :class:`SubagentManager`.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest
from aiohttp import web

from secbot.agent.subagent import SubagentStatus
from secbot.api.agents import handle_list_agents


# ---------------------------------------------------------------------------
# Fixtures — minimal stand-ins for ExpertAgentSpec / AgentRegistry. We keep
# this independent from ``secbot.agents.registry`` to avoid pulling YAML
# loaders / disk I/O into a unit test.
# ---------------------------------------------------------------------------


@dataclass
class _FakeSpec:
    name: str
    display_name: str = ""
    description: str = ""
    scoped_skills: tuple[str, ...] = ()
    max_iterations: int = 10
    source_path: Any = None
    available: bool = True
    required_binaries: tuple[str, ...] = ()
    missing_binaries: tuple[str, ...] = ()


class _FakeRegistry:
    def __init__(self, specs: list[_FakeSpec]):
        self._specs = specs

    def __iter__(self):
        return iter(self._specs)


class _StubManager:
    def __init__(self, statuses: dict[str, SubagentStatus] | None = None):
        self._task_statuses = statuses or {}


@dataclass
class _StubRequest:
    """Captures the ``request.app`` + ``request.query`` surface used by the handler."""

    app: dict[str, Any] = field(default_factory=dict)
    query: dict[str, str] = field(default_factory=dict)


def _body(resp: web.Response) -> dict[str, Any]:
    return json.loads(resp.body)


# ---------------------------------------------------------------------------
# Default response — must NOT include runtime fields (byte-stable contract).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_response_excludes_runtime_fields() -> None:
    registry = _FakeRegistry([
        _FakeSpec(name="alpha", display_name="Alpha", description="desc"),
    ])
    request = _StubRequest(
        app={"agent_registry": registry, "subagent_manager": _StubManager()},
        query={},
    )
    resp = await handle_list_agents(request)  # type: ignore[arg-type]
    body = _body(resp)
    assert list(body.keys()) == ["agents"]
    [entry] = body["agents"]
    # No runtime fields without ``?include_status=true``.
    for forbidden in ("status", "current_task_id", "last_heartbeat_at", "progress"):
        assert forbidden not in entry
    # Static fields preserved in their canonical order.
    assert list(entry.keys()) == [
        "name",
        "display_name",
        "description",
        "scoped_skills",
        "max_iterations",
        "source_path",
        "available",
        "required_binaries",
        "missing_binaries",
    ]


@pytest.mark.asyncio
async def test_default_response_byte_stable_regardless_of_subagent_manager() -> None:
    """Same registry → identical bytes whether or not a SubagentManager is
    attached. Validates the byte-stability acceptance criterion (验收6).
    """
    registry = _FakeRegistry([
        _FakeSpec(name="alpha"),
        _FakeSpec(name="beta"),
    ])
    req_no_mgr = _StubRequest(app={"agent_registry": registry}, query={})
    req_with_mgr = _StubRequest(
        app={"agent_registry": registry, "subagent_manager": _StubManager()},
        query={},
    )
    resp_a = await handle_list_agents(req_no_mgr)  # type: ignore[arg-type]
    resp_b = await handle_list_agents(req_with_mgr)  # type: ignore[arg-type]
    assert resp_a.body == resp_b.body


# ---------------------------------------------------------------------------
# include_status=true — runtime enrichment.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_include_status_offline_when_no_manager() -> None:
    registry = _FakeRegistry([_FakeSpec(name="alpha")])
    request = _StubRequest(
        app={"agent_registry": registry},
        query={"include_status": "true"},
    )
    [entry] = _body(await handle_list_agents(request))["agents"]  # type: ignore[arg-type]
    assert entry["status"] == "offline"
    assert entry["current_task_id"] is None
    assert entry["progress"] is None
    assert entry["last_heartbeat_at"] is None


@pytest.mark.asyncio
async def test_include_status_idle_when_manager_has_no_running_tasks() -> None:
    registry = _FakeRegistry([_FakeSpec(name="alpha"), _FakeSpec(name="beta")])
    request = _StubRequest(
        app={"agent_registry": registry, "subagent_manager": _StubManager()},
        query={"include_status": "true"},
    )
    body = _body(await handle_list_agents(request))  # type: ignore[arg-type]
    for entry in body["agents"]:
        assert entry["status"] == "idle"
        assert entry["current_task_id"] is None
        assert entry["progress"] is None
        assert entry["last_heartbeat_at"] is None


@pytest.mark.asyncio
async def test_include_status_running_propagates_task_and_heartbeat() -> None:
    now = time.time()
    status = SubagentStatus(
        task_id="task-1",
        label="alpha label",
        task_description="...",
        started_at=time.monotonic(),
        agent_name="alpha",
        last_heartbeat_at=now,
    )
    registry = _FakeRegistry([_FakeSpec(name="alpha"), _FakeSpec(name="beta")])
    request = _StubRequest(
        app={
            "agent_registry": registry,
            "subagent_manager": _StubManager({"task-1": status}),
        },
        query={"include_status": "true"},
    )
    body = _body(await handle_list_agents(request))  # type: ignore[arg-type]
    by_name = {e["name"]: e for e in body["agents"]}
    assert by_name["alpha"]["status"] == "running"
    assert by_name["alpha"]["current_task_id"] == "task-1"
    assert by_name["alpha"]["progress"] is None
    assert isinstance(by_name["alpha"]["last_heartbeat_at"], str)
    assert by_name["alpha"]["last_heartbeat_at"].endswith("+00:00")
    # Other agents fall back to idle (manager attached but no matching status).
    assert by_name["beta"]["status"] == "idle"


@pytest.mark.asyncio
async def test_include_status_last_heartbeat_wins_for_same_agent() -> None:
    """If two SubagentStatus rows share the same ``agent_name``, the entry
    with the most recent ``last_heartbeat_at`` takes the slot.
    """
    older = SubagentStatus(
        task_id="t-old",
        label="x",
        task_description="...",
        started_at=time.monotonic(),
        agent_name="alpha",
        last_heartbeat_at=time.time() - 100,
    )
    newer = SubagentStatus(
        task_id="t-new",
        label="x",
        task_description="...",
        started_at=time.monotonic(),
        agent_name="alpha",
        last_heartbeat_at=time.time(),
    )
    registry = _FakeRegistry([_FakeSpec(name="alpha")])
    request = _StubRequest(
        app={
            "agent_registry": registry,
            "subagent_manager": _StubManager({"old": older, "new": newer}),
        },
        query={"include_status": "true"},
    )
    [entry] = _body(await handle_list_agents(request))["agents"]  # type: ignore[arg-type]
    assert entry["current_task_id"] == "t-new"


@pytest.mark.asyncio
async def test_include_status_falsy_values_keep_default_shape() -> None:
    """``?include_status=false`` / ``?include_status=`` MUST behave like
    omitting the query: no runtime fields appended.
    """
    registry = _FakeRegistry([_FakeSpec(name="alpha")])
    for value in ("false", "0", "no", ""):
        request = _StubRequest(
            app={"agent_registry": registry, "subagent_manager": _StubManager()},
            query={"include_status": value},
        )
        [entry] = _body(await handle_list_agents(request))["agents"]  # type: ignore[arg-type]
        assert "status" not in entry, f"value={value!r} should not enrich"

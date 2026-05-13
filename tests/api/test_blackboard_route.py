"""Tests for ``GET /api/blackboard`` (P0/B2).

Spec: ``.trellis/spec/backend/dashboard-aggregation.md`` §2.7.

The handler is wired through aiohttp via :func:`create_app`. We exercise the
handler directly with a stub ``request.app`` mapping to keep the test surface
minimal — the route is a thin shim over ``BlackboardRegistry``.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from aiohttp import web

from secbot.agent.blackboard import BlackboardRegistry
from secbot.api.blackboard import handle_get_blackboard


class _StubRequest:
    """Tiny stand-in for :class:`aiohttp.web.Request` used by the handler.

    The handler only touches ``request.query`` and ``request.app.get(...)``,
    so a minimal ``query`` dict + ``app`` mapping covers the surface.
    """

    def __init__(self, query: dict[str, str], app: dict[str, Any]):
        self.query = query
        self.app = app


def _body(resp: web.Response) -> dict[str, Any]:
    return json.loads(resp.body)


@pytest.mark.asyncio
async def test_missing_chat_id_returns_400() -> None:
    resp = await handle_get_blackboard(_StubRequest({}, {}))
    assert resp.status == 400
    assert "missing chat_id" in _body(resp)["error"]


@pytest.mark.asyncio
async def test_no_registry_returns_empty_list() -> None:
    resp = await handle_get_blackboard(
        _StubRequest({"chat_id": "abc"}, {})
    )
    assert resp.status == 200
    body = _body(resp)
    assert body == {"chat_id": "abc", "entries": []}


@pytest.mark.asyncio
async def test_unknown_chat_id_does_not_create_board() -> None:
    """Reads must NOT side-effect the registry; spurious chat_ids stay
    untracked. Spec: D3 / dashboard-aggregation.md §2.7.
    """
    registry = BlackboardRegistry()
    resp = await handle_get_blackboard(
        _StubRequest({"chat_id": "ghost"}, {"blackboard_registry": registry})
    )
    assert resp.status == 200
    assert _body(resp) == {"chat_id": "ghost", "entries": []}
    assert "ghost" not in registry.chat_ids()


@pytest.mark.asyncio
async def test_existing_chat_id_returns_entries_with_kind() -> None:
    registry = BlackboardRegistry()
    board = await registry.get_or_create("chat-1")
    await board.write("scanner", "[finding] open port 80")
    await board.write("scanner", "no prefix here")

    resp = await handle_get_blackboard(
        _StubRequest({"chat_id": "chat-1"}, {"blackboard_registry": registry})
    )
    assert resp.status == 200
    body = _body(resp)
    assert body["chat_id"] == "chat-1"
    assert len(body["entries"]) == 2
    kinds = [row["kind"] for row in body["entries"]]
    assert kinds == ["finding", None]
    # Canonical entry shape — id / agent_name / text / timestamp / kind.
    for row in body["entries"]:
        assert set(row.keys()) >= {"id", "agent_name", "text", "timestamp", "kind"}


@pytest.mark.asyncio
async def test_chat_id_isolation_across_boards() -> None:
    registry = BlackboardRegistry()
    await (await registry.get_or_create("chat-a")).write("a", "[milestone] A")
    await (await registry.get_or_create("chat-b")).write("b", "[blocker] B")

    resp_a = await handle_get_blackboard(
        _StubRequest({"chat_id": "chat-a"}, {"blackboard_registry": registry})
    )
    resp_b = await handle_get_blackboard(
        _StubRequest({"chat_id": "chat-b"}, {"blackboard_registry": registry})
    )
    body_a = _body(resp_a)
    body_b = _body(resp_b)
    assert [row["text"] for row in body_a["entries"]] == ["[milestone] A"]
    assert [row["text"] for row in body_b["entries"]] == ["[blocker] B"]

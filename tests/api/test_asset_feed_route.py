"""Tests for ``GET /api/assets`` (PR-3 of ``05-17-bb-realtime-notify``).

Mirrors ``test_blackboard_route.py`` — the handler is exercised directly
with a minimal stub request, since it is a thin shim over
:class:`AssetFeedRegistry`.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from aiohttp import web

from secbot.agent.asset_feed import AssetFeedRegistry
from secbot.api.asset_feed import handle_get_assets


class _StubRequest:
    def __init__(self, query: dict[str, str], app: dict[str, Any]):
        self.query = query
        self.app = app


def _body(resp: web.Response) -> dict[str, Any]:
    return json.loads(resp.body)


@pytest.mark.asyncio
async def test_missing_chat_id_returns_400() -> None:
    resp = await handle_get_assets(_StubRequest({}, {}))
    assert resp.status == 400
    assert "missing chat_id" in _body(resp)["error"]


@pytest.mark.asyncio
async def test_no_registry_returns_empty_payload() -> None:
    resp = await handle_get_assets(_StubRequest({"chat_id": "abc"}, {}))
    assert resp.status == 200
    assert _body(resp) == {
        "chat_id": "abc",
        "entries": [],
        "latest_id": 0,
        "counts": {},
    }


@pytest.mark.asyncio
async def test_unknown_chat_does_not_create_feed() -> None:
    """Reads must NOT side-effect the registry: spurious chat_ids stay
    untracked. Mirrors the blackboard route invariant."""
    registry = AssetFeedRegistry()
    resp = await handle_get_assets(
        _StubRequest({"chat_id": "ghost"}, {"asset_feed_registry": registry})
    )
    assert resp.status == 200
    assert _body(resp)["entries"] == []
    assert "ghost" not in registry.chat_ids()


@pytest.mark.asyncio
async def test_existing_chat_returns_entries_with_canonical_shape() -> None:
    registry = AssetFeedRegistry()
    feed = await registry.get_or_create("chat-1")
    await feed.append(kind="url", agent_name="crawl_web", payload={"url": "/a"})
    await feed.append(kind="port", agent_name="port_scan", payload={"host": "h", "port": 22})

    resp = await handle_get_assets(
        _StubRequest({"chat_id": "chat-1"}, {"asset_feed_registry": registry})
    )
    body = _body(resp)
    assert body["chat_id"] == "chat-1"
    assert body["latest_id"] == 2
    assert body["counts"] == {"url": 1, "port": 1}
    assert len(body["entries"]) == 2
    for row in body["entries"]:
        assert set(row.keys()) >= {"id", "kind", "agent_name", "payload", "created_at"}


@pytest.mark.asyncio
async def test_kind_filter_query_param() -> None:
    registry = AssetFeedRegistry()
    feed = await registry.get_or_create("c1")
    await feed.append(kind="url", agent_name="a", payload={"u": 1})
    await feed.append(kind="port", agent_name="a", payload={"p": 22})
    await feed.append(kind="url", agent_name="a", payload={"u": 2})

    resp = await handle_get_assets(
        _StubRequest(
            {"chat_id": "c1", "kind": "URL"},  # case-insensitive
            {"asset_feed_registry": registry},
        )
    )
    body = _body(resp)
    assert [r["id"] for r in body["entries"]] == [1, 3]
    # Counts always reflect the full feed, not the filtered slice.
    assert body["counts"] == {"url": 2, "port": 1}


@pytest.mark.asyncio
async def test_since_id_cursor() -> None:
    registry = AssetFeedRegistry()
    feed = await registry.get_or_create("c1")
    await feed.append(kind="url", agent_name="a", payload={"u": 1})
    await feed.append(kind="url", agent_name="a", payload={"u": 2})
    await feed.append(kind="url", agent_name="a", payload={"u": 3})

    resp = await handle_get_assets(
        _StubRequest(
            {"chat_id": "c1", "since_id": "2"},
            {"asset_feed_registry": registry},
        )
    )
    body = _body(resp)
    assert [r["id"] for r in body["entries"]] == [3]


@pytest.mark.asyncio
async def test_invalid_since_id_is_ignored() -> None:
    registry = AssetFeedRegistry()
    feed = await registry.get_or_create("c1")
    await feed.append(kind="url", agent_name="a", payload={"u": 1})
    resp = await handle_get_assets(
        _StubRequest(
            {"chat_id": "c1", "since_id": "abc"},
            {"asset_feed_registry": registry},
        )
    )
    body = _body(resp)
    assert [r["id"] for r in body["entries"]] == [1]

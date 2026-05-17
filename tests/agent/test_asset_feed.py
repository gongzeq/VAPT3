"""Tests for :mod:`secbot.agent.asset_feed`.

Covers PR-1 of ``05-17-bb-realtime-notify``: the in-memory per-chat asset
feed and registry. Mirrors the structure of ``test_blackboard.py``.
"""

from __future__ import annotations

import asyncio

import pytest

from secbot.agent.asset_feed import AssetFeed, AssetFeedRegistry


@pytest.mark.asyncio
async def test_append_assigns_monotonic_ids() -> None:
    feed = AssetFeed()
    a = await feed.append(kind="url", agent_name="crawl_web", payload={"url": "/a"})
    b = await feed.append(kind="url", agent_name="crawl_web", payload={"url": "/b"})
    c = await feed.append(kind="port", agent_name="port_scan", payload={"port": 80})
    assert a.id == 1
    assert b.id == 2
    assert c.id == 3
    assert feed.latest_id == 3
    assert len(feed) == 3


@pytest.mark.asyncio
async def test_payload_is_copied() -> None:
    """The feed must not retain a reference to caller-mutable dicts."""
    feed = AssetFeed()
    payload = {"url": "/x"}
    entry = await feed.append(kind="url", agent_name="a", payload=payload)
    payload["url"] = "/MUTATED"
    assert entry.payload == {"url": "/x"}


@pytest.mark.asyncio
async def test_since_filters_by_id_and_kind() -> None:
    feed = AssetFeed()
    await feed.append(kind="url", agent_name="a", payload={"url": "/1"})
    await feed.append(kind="port", agent_name="a", payload={"port": 22})
    await feed.append(kind="url", agent_name="a", payload={"url": "/3"})

    # Cursor: skip first two, only id=3 returned.
    after = await feed.since(since_id=2)
    assert [e.id for e in after] == [3]

    # Kind filter alone: full snapshot of url entries.
    urls = await feed.since(kind="url")
    assert [e.id for e in urls] == [1, 3]

    # Combined: kind + cursor.
    new_urls = await feed.since(since_id=1, kind="url")
    assert [e.id for e in new_urls] == [3]


@pytest.mark.asyncio
async def test_since_limit_caps_result() -> None:
    feed = AssetFeed()
    for i in range(5):
        await feed.append(kind="url", agent_name="a", payload={"i": i})
    capped = await feed.since(limit=3)
    assert len(capped) == 3


@pytest.mark.asyncio
async def test_counts_and_group_by_kind() -> None:
    feed = AssetFeed()
    await feed.append(kind="url", agent_name="a", payload={"i": 1})
    await feed.append(kind="url", agent_name="a", payload={"i": 2})
    await feed.append(kind="port", agent_name="b", payload={"i": 3})
    counts = await feed.counts_by_kind()
    assert counts == {"url": 2, "port": 1}
    grouped = await feed.group_by_kind()
    assert sorted(grouped.keys()) == ["port", "url"]
    assert [e.id for e in grouped["url"]] == [1, 2]


@pytest.mark.asyncio
async def test_set_on_append_callback_fired() -> None:
    feed = AssetFeed()
    seen: list[int] = []

    def cb(entry):  # noqa: ANN001
        seen.append(entry.id)

    feed.set_on_append(cb)
    await feed.append(kind="url", agent_name="a", payload={"u": "/1"})
    await feed.append(kind="url", agent_name="a", payload={"u": "/2"})
    assert seen == [1, 2]

    # Unbinding restores no-op behaviour.
    feed.set_on_append(None)
    await feed.append(kind="url", agent_name="a", payload={"u": "/3"})
    assert seen == [1, 2]


@pytest.mark.asyncio
async def test_on_append_exception_is_swallowed() -> None:
    feed = AssetFeed()

    def boom(_entry):  # noqa: ANN001
        raise RuntimeError("broadcaster down")

    feed.set_on_append(boom)
    # Must not propagate; entry must still be persisted.
    entry = await feed.append(kind="url", agent_name="a", payload={"u": "/1"})
    assert entry.id == 1
    rows = await feed.since()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_concurrent_appends_get_unique_ids() -> None:
    feed = AssetFeed()

    async def push(i: int) -> None:
        await feed.append(kind="url", agent_name="a", payload={"i": i})

    await asyncio.gather(*(push(i) for i in range(50)))
    rows = await feed.since()
    ids = sorted(e.id for e in rows)
    assert ids == list(range(1, 51))


@pytest.mark.asyncio
async def test_registry_isolates_chats() -> None:
    registry = AssetFeedRegistry()
    feed_a = await registry.get_or_create("chat-a")
    feed_b = await registry.get_or_create("chat-b")
    assert feed_a is not feed_b

    await feed_a.append(kind="url", agent_name="x", payload={"u": "a"})
    rows_b = await feed_b.since()
    assert rows_b == []
    rows_a = await feed_a.since()
    assert len(rows_a) == 1


@pytest.mark.asyncio
async def test_registry_get_does_not_create() -> None:
    registry = AssetFeedRegistry()
    assert await registry.get("ghost") is None
    assert "ghost" not in registry.chat_ids()


@pytest.mark.asyncio
async def test_registry_drop_removes_feed() -> None:
    registry = AssetFeedRegistry()
    await registry.get_or_create("chat-x")
    assert "chat-x" in registry.chat_ids()
    await registry.drop("chat-x")
    assert "chat-x" not in registry.chat_ids()
    assert await registry.get("chat-x") is None

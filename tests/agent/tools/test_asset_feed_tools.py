"""Tests for :class:`AssetPushTool` and :class:`ReadAssetsTool`.

PR-1 of ``05-17-bb-realtime-notify``: the sub-agent tool surface for
real-time discrete asset publishing + cursor-based consumption.
"""

from __future__ import annotations

import json

import pytest

from secbot.agent.asset_feed import AssetFeed
from secbot.agent.tools.asset_feed import AssetPushTool, ReadAssetsTool
from secbot.bus.queue import MessageBus


@pytest.mark.asyncio
async def test_asset_push_writes_to_feed_without_bus() -> None:
    """Without a bus the push must still persist the entry (best-effort wake-up)."""
    feed = AssetFeed()
    tool = AssetPushTool(feed=feed, agent_name="crawl_web")
    out = await tool.execute(kind="url", payload={"url": "/admin"})
    assert "asset pushed" in out
    assert "id=1" in out
    rows = await feed.since()
    assert len(rows) == 1
    assert rows[0].kind == "url"
    assert rows[0].agent_name == "crawl_web"
    assert rows[0].payload == {"url": "/admin"}


@pytest.mark.asyncio
async def test_asset_push_kind_normalised_to_lower() -> None:
    feed = AssetFeed()
    tool = AssetPushTool(feed=feed)
    await tool.execute(kind="URL", payload={"url": "/x"})
    rows = await feed.since()
    assert rows[0].kind == "url"


@pytest.mark.asyncio
async def test_asset_push_unknown_kind_is_flagged_in_message() -> None:
    feed = AssetFeed()
    tool = AssetPushTool(feed=feed)
    out = await tool.execute(kind="custom_kind", payload={})
    assert "non-standard" in out
    rows = await feed.since()
    assert rows[0].kind == "custom_kind"


@pytest.mark.asyncio
async def test_asset_push_rejects_empty_kind() -> None:
    feed = AssetFeed()
    tool = AssetPushTool(feed=feed)
    out = await tool.execute(kind="", payload={"x": 1})
    assert out.startswith("Error")
    assert len(feed) == 0


@pytest.mark.asyncio
async def test_asset_push_rejects_non_dict_payload() -> None:
    feed = AssetFeed()
    tool = AssetPushTool(feed=feed)
    out = await tool.execute(kind="url", payload="not a dict")
    assert out.startswith("Error")
    assert len(feed) == 0


@pytest.mark.asyncio
async def test_asset_push_emits_inbound_with_injected_event() -> None:
    feed = AssetFeed()
    bus = MessageBus()
    tool = AssetPushTool(
        feed=feed,
        bus=bus,
        origin={"channel": "websocket", "chat_id": "abc"},
        agent_name="crawl_web",
    )
    await tool.execute(kind="url", payload={"url": "/login"})
    msg = await bus.consume_inbound()
    assert msg.channel == "system"
    assert msg.metadata.get("injected_event") == "asset_discovered"
    assert msg.metadata.get("asset_kind") == "url"
    assert msg.metadata.get("asset_id") == 1
    assert msg.metadata.get("asset_agent") == "crawl_web"
    # Routes back to the originating session queue.
    assert msg.session_key_override == "websocket:abc"


@pytest.mark.asyncio
async def test_asset_push_resolves_callable_origin() -> None:
    feed = AssetFeed()
    bus = MessageBus()
    captured: dict = {"channel": "websocket", "chat_id": "c1"}

    def origin_provider() -> dict:
        return captured

    tool = AssetPushTool(feed=feed, bus=bus, origin=origin_provider)
    await tool.execute(kind="port", payload={"host": "h", "port": 22})
    msg = await bus.consume_inbound()
    assert msg.session_key_override == "websocket:c1"

    # Origin can return None — push still succeeds, no inbound emitted.
    captured.clear()

    def empty_origin() -> None:
        return None

    tool2 = AssetPushTool(feed=feed, bus=bus, origin=empty_origin)
    out = await tool2.execute(kind="vuln", payload={"cve": "CVE-1"})
    assert "asset pushed" in out
    assert bus.inbound.empty()


@pytest.mark.asyncio
async def test_read_assets_returns_no_new_assets_on_empty() -> None:
    feed = AssetFeed()
    tool = ReadAssetsTool(feed=feed)
    out = await tool.execute()
    assert out == "No new assets."


@pytest.mark.asyncio
async def test_read_assets_returns_full_snapshot_as_json() -> None:
    feed = AssetFeed()
    await feed.append(kind="url", agent_name="a", payload={"url": "/1"})
    await feed.append(kind="port", agent_name="b", payload={"port": 22})
    tool = ReadAssetsTool(feed=feed)
    out = await tool.execute()
    rows = json.loads(out)
    assert [r["id"] for r in rows] == [1, 2]
    assert {r["kind"] for r in rows} == {"url", "port"}


@pytest.mark.asyncio
async def test_read_assets_filters_kind_and_since_id() -> None:
    feed = AssetFeed()
    await feed.append(kind="url", agent_name="a", payload={"u": 1})
    await feed.append(kind="port", agent_name="a", payload={"p": 22})
    await feed.append(kind="url", agent_name="a", payload={"u": 2})
    tool = ReadAssetsTool(feed=feed)

    out_url = await tool.execute(kind="url")
    rows = json.loads(out_url)
    assert [r["id"] for r in rows] == [1, 3]

    out_after = await tool.execute(since_id=2)
    rows = json.loads(out_after)
    assert [r["id"] for r in rows] == [3]

    out_combined = await tool.execute(kind="url", since_id=1)
    rows = json.loads(out_combined)
    assert [r["id"] for r in rows] == [3]


@pytest.mark.asyncio
async def test_read_assets_resolves_callable_feed() -> None:
    feeds = [AssetFeed(), AssetFeed()]
    state = {"idx": 0}

    def provider() -> AssetFeed:
        return feeds[state["idx"]]

    tool = ReadAssetsTool(feed=provider)

    await feeds[0].append(kind="url", agent_name="a", payload={"u": 1})
    out = await tool.execute()
    rows = json.loads(out)
    assert len(rows) == 1

    state["idx"] = 1
    out2 = await tool.execute()
    assert out2 == "No new assets."


def test_read_assets_is_read_only() -> None:
    """Orchestrator may inspect the feed without consent prompts."""
    tool = ReadAssetsTool(feed=AssetFeed())
    assert tool.read_only is True

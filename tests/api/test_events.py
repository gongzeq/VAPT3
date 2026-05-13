"""Tests for the activity event stream HTTP endpoint (P2/R2)."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from secbot.channels import notifications as notif_module
from secbot.channels.notifications import (
    DEFAULT_BUFFER_SIZE,
    DEFAULT_EVENTS_WINDOW_SECONDS,
    EventBuffer,
    get_event_buffer,
    reset_event_buffer,
)
from secbot.channels.websocket import WebSocketChannel


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _isolated_events(monkeypatch: pytest.MonkeyPatch):
    """Each test starts with a fresh singleton and no env overrides."""
    monkeypatch.delenv("SECBOT_EVENTS_BUFFER_SIZE", raising=False)
    monkeypatch.delenv("SECBOT_EVENTS_WINDOW_SECONDS", raising=False)
    reset_event_buffer()
    try:
        yield
    finally:
        reset_event_buffer()


@pytest.fixture
def channel() -> WebSocketChannel:
    bus = MagicMock()
    bus.publish_inbound = AsyncMock()
    ch = WebSocketChannel(
        {
            "enabled": True,
            "allowFrom": ["*"],
            "host": "127.0.0.1",
            "port": 0,
            "path": "/",
            "websocketRequiresToken": False,
        },
        bus,
    )
    ch._api_tokens["live"] = time.monotonic() + 60.0
    return ch


class _Req:
    def __init__(self, path: str, *, token: str | None = "live"):
        self.path = path
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}


def _body(resp) -> dict[str, Any]:
    return json.loads(resp.body)


# ---------------------------------------------------------------------------
# EventBuffer unit tests
# ---------------------------------------------------------------------------
class TestEventBufferUnit:
    def test_publish_assigns_evt_prefix_and_iso_timestamp(self) -> None:
        buf = EventBuffer()
        item = buf.publish(level="info", source="port_scan", message="m")
        assert item["id"].startswith("evt-")
        assert len(item["id"]) == 4 + 26
        assert "T" in item["timestamp"]  # ISO-8601

    def test_publish_defaults_timestamp_to_utc(self) -> None:
        buf = EventBuffer()
        before = datetime.now(timezone.utc)
        item = buf.publish(level="info", source="port_scan", message="m")
        after = datetime.now(timezone.utc)
        ts = datetime.fromisoformat(item["timestamp"])
        assert before - timedelta(seconds=1) <= ts <= after + timedelta(seconds=1)

    def test_publish_newest_first_order(self) -> None:
        buf = EventBuffer()
        a = buf.publish(level="info", source="port_scan", message="a")
        b = buf.publish(level="warning", source="weak_password", message="b")
        snap = buf.snapshot()
        assert [item["id"] for item in snap] == [b["id"], a["id"]]

    def test_maxlen_evicts_oldest(self) -> None:
        buf = EventBuffer(maxlen=2)
        a = buf.publish(level="info", source="port_scan", message="a")
        b = buf.publish(level="info", source="port_scan", message="b")
        c = buf.publish(level="info", source="port_scan", message="c")
        ids = [item["id"] for item in buf.snapshot()]
        assert ids == [c["id"], b["id"]]
        assert a["id"] not in ids

    def test_env_events_buffer_size_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SECBOT_EVENTS_BUFFER_SIZE", "4")
        buf = EventBuffer(maxlen=99)
        assert buf.maxlen == 4

    def test_env_window_seconds_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SECBOT_EVENTS_WINDOW_SECONDS", "60")
        buf = EventBuffer()
        assert buf.default_window_seconds == 60

    def test_env_window_seconds_invalid_falls_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SECBOT_EVENTS_WINDOW_SECONDS", "xyz")
        buf = EventBuffer()
        assert buf.default_window_seconds == DEFAULT_EVENTS_WINDOW_SECONDS

    def test_default_constructor_uses_module_defaults(self) -> None:
        buf = EventBuffer()
        assert buf.maxlen == DEFAULT_BUFFER_SIZE
        assert buf.default_window_seconds == DEFAULT_EVENTS_WINDOW_SECONDS

    def test_filter_since_excludes_older_events(self) -> None:
        buf = EventBuffer()
        now = datetime.now(timezone.utc)
        # Inject an old event (10 min ago) + a recent one (30s ago).
        old = buf.publish(
            level="info",
            source="port_scan",
            message="old",
            timestamp=now - timedelta(minutes=10),
        )
        recent = buf.publish(
            level="info",
            source="port_scan",
            message="recent",
            timestamp=now - timedelta(seconds=30),
        )
        # Default window (5 min) picks only the recent event.
        got = buf.filter()
        assert [item["id"] for item in got] == [recent["id"]]
        assert old["id"] not in {item["id"] for item in got}

    def test_filter_since_explicit_cutoff(self) -> None:
        buf = EventBuffer()
        now = datetime.now(timezone.utc)
        older = buf.publish(
            level="info",
            source="port_scan",
            message="older",
            timestamp=now - timedelta(minutes=30),
        )
        middle = buf.publish(
            level="info",
            source="port_scan",
            message="middle",
            timestamp=now - timedelta(minutes=15),
        )
        newest = buf.publish(
            level="info",
            source="port_scan",
            message="newest",
            timestamp=now - timedelta(minutes=1),
        )
        got = buf.filter(since=now - timedelta(minutes=20))
        ids = [item["id"] for item in got]
        assert newest["id"] in ids
        assert middle["id"] in ids
        assert older["id"] not in ids

    def test_filter_limit_clamps_results(self) -> None:
        buf = EventBuffer()
        now = datetime.now(timezone.utc)
        for i in range(10):
            buf.publish(
                level="info",
                source="port_scan",
                message=f"m{i}",
                timestamp=now - timedelta(seconds=i),
            )
        got = buf.filter(limit=3)
        assert len(got) == 3

    def test_filter_limit_zero_returns_empty(self) -> None:
        buf = EventBuffer()
        buf.publish(level="info", source="port_scan", message="m")
        assert buf.filter(limit=0) == []

    def test_naive_datetime_normalised_to_utc(self) -> None:
        buf = EventBuffer()
        naive = datetime(2026, 1, 1, 0, 0, 0)
        item = buf.publish(
            level="info", source="port_scan", message="m", timestamp=naive
        )
        # Timestamp serialised with explicit offset.
        assert "+00:00" in item["timestamp"]

    def test_unknown_level_and_source_accepted(self) -> None:
        buf = EventBuffer()
        item = buf.publish(level="trace", source="custom", message="m")
        assert item["level"] == "trace"
        assert item["source"] == "custom"


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
class TestEventBufferSingleton:
    def test_get_returns_same_instance(self) -> None:
        a = get_event_buffer()
        b = get_event_buffer()
        assert a is b

    def test_reset_drops_singleton(self) -> None:
        a = get_event_buffer()
        reset_event_buffer()
        b = get_event_buffer()
        assert a is not b

    def test_reset_clears_module_global(self) -> None:
        get_event_buffer()
        assert notif_module._event_buffer is not None
        reset_event_buffer()
        assert notif_module._event_buffer is None


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------
class TestEventsHttp:
    def test_unauthenticated_returns_401(self, channel: WebSocketChannel) -> None:
        resp = channel._handle_events_list(_Req("/api/events", token=None))
        assert resp.status_code == 401

    def test_empty_buffer_returns_empty_items(self, channel: WebSocketChannel) -> None:
        resp = channel._handle_events_list(_Req("/api/events"))
        assert resp.status_code == 200
        assert _body(resp) == {"items": []}

    def test_default_window_hides_old_events(
        self, channel: WebSocketChannel
    ) -> None:
        buf = get_event_buffer()
        now = datetime.now(timezone.utc)
        old = buf.publish(
            level="info",
            source="port_scan",
            message="old",
            timestamp=now - timedelta(hours=1),
        )
        recent = buf.publish(
            level="info",
            source="port_scan",
            message="recent",
            timestamp=now - timedelta(seconds=10),
        )
        resp = channel._handle_events_list(_Req("/api/events"))
        ids = [item["id"] for item in _body(resp)["items"]]
        assert recent["id"] in ids
        assert old["id"] not in ids

    def test_since_filter_accepts_offset_timestamp(
        self, channel: WebSocketChannel
    ) -> None:
        buf = get_event_buffer()
        # Seed an event 2 hours ago — should be visible with explicit
        # ``since=3h ago`` but hidden with default window.
        ts = datetime.now(timezone.utc) - timedelta(hours=2)
        old = buf.publish(
            level="info", source="port_scan", message="old", timestamp=ts
        )
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat(
            timespec="seconds"
        )
        resp = channel._handle_events_list(
            _Req(f"/api/events?since={cutoff}")
        )
        ids = [item["id"] for item in _body(resp)["items"]]
        assert old["id"] in ids

    def test_limit_defaults_to_50(self, channel: WebSocketChannel) -> None:
        buf = get_event_buffer()
        now = datetime.now(timezone.utc)
        for i in range(60):
            buf.publish(
                level="info",
                source="port_scan",
                message=f"m{i}",
                timestamp=now - timedelta(seconds=i),
            )
        resp = channel._handle_events_list(_Req("/api/events"))
        assert len(_body(resp)["items"]) == 50

    def test_limit_clamped_to_500(self, channel: WebSocketChannel) -> None:
        buf = get_event_buffer()
        now = datetime.now(timezone.utc)
        for i in range(3):
            buf.publish(
                level="info",
                source="port_scan",
                message=f"m{i}",
                timestamp=now - timedelta(seconds=i),
            )
        # Clamp preserves the natural 3 rows but accepts the oversize param.
        resp = channel._handle_events_list(_Req("/api/events?limit=9999"))
        assert resp.status_code == 200
        assert len(_body(resp)["items"]) == 3

    def test_invalid_limit_returns_400(self, channel: WebSocketChannel) -> None:
        resp = channel._handle_events_list(_Req("/api/events?limit=abc"))
        assert resp.status_code == 400

    def test_invalid_since_returns_400(self, channel: WebSocketChannel) -> None:
        resp = channel._handle_events_list(_Req("/api/events?since=not-a-date"))
        assert resp.status_code == 400

    def test_empty_since_uses_default_window(
        self, channel: WebSocketChannel
    ) -> None:
        # ``since=`` (blank) must behave the same as absent ``since``.
        buf = get_event_buffer()
        now = datetime.now(timezone.utc)
        old = buf.publish(
            level="info",
            source="port_scan",
            message="old",
            timestamp=now - timedelta(hours=1),
        )
        recent = buf.publish(
            level="info",
            source="port_scan",
            message="recent",
            timestamp=now - timedelta(seconds=5),
        )
        resp = channel._handle_events_list(_Req("/api/events?since="))
        ids = [item["id"] for item in _body(resp)["items"]]
        assert recent["id"] in ids
        assert old["id"] not in ids

    def test_response_items_contain_documented_fields(
        self, channel: WebSocketChannel
    ) -> None:
        buf = get_event_buffer()
        buf.publish(
            level="critical",
            source="weak_password",
            message="10.0.0.1 SSH 弱口令",
            task_id="TASK-1",
        )
        resp = channel._handle_events_list(_Req("/api/events"))
        items = _body(resp)["items"]
        assert len(items) == 1
        entry = items[0]
        assert set(entry.keys()) >= {
            "id",
            "timestamp",
            "level",
            "source",
            "task_id",
            "message",
        }
        assert entry["level"] == "critical"
        assert entry["source"] == "weak_password"
        assert entry["task_id"] == "TASK-1"


# ---------------------------------------------------------------------------
# B7: chat_id / category filtering (PRD 05-12-multi-agent-obs-trace)
# ---------------------------------------------------------------------------
class TestEventsTraceFilters:
    """Right-Rail Trace Tab query-filter contract.

    Three canonical paths per PRD:
      1. ``?chat_id=<id>`` — only rows whose ``chat_id`` matches.
      2. ``?category=a,b`` — inclusion filter over multiple categories.
      3. No query params — backwards compatible with the pre-P1 shape.
    """

    def _seed_cross_chat(self) -> None:
        """Seed 4 events across 2 chats × 3 categories so every test
        starts from the same fixture. Timestamps are spaced 1s apart so
        the default 5-minute window picks up every row."""
        buf = get_event_buffer()
        now = datetime.now(timezone.utc)
        buf.publish(
            level="info",
            source="orchestrator",
            message="A thought",
            chat_id="chat-A",
            category="thought",
            timestamp=now - timedelta(seconds=4),
        )
        buf.publish(
            level="info",
            source="port_scan",
            message="A tool_call",
            chat_id="chat-A",
            category="tool_call",
            timestamp=now - timedelta(seconds=3),
        )
        buf.publish(
            level="ok",
            source="port_scan",
            message="A tool_result",
            chat_id="chat-A",
            category="tool_result",
            timestamp=now - timedelta(seconds=2),
        )
        buf.publish(
            level="info",
            source="orchestrator",
            message="B thought",
            chat_id="chat-B",
            category="thought",
            timestamp=now - timedelta(seconds=1),
        )

    def test_chat_id_filter_returns_only_matching_rows(
        self, channel: WebSocketChannel
    ) -> None:
        self._seed_cross_chat()
        resp = channel._handle_events_list(_Req("/api/events?chat_id=chat-A"))
        assert resp.status_code == 200
        items = _body(resp)["items"]
        assert len(items) == 3
        assert {item["chat_id"] for item in items} == {"chat-A"}

    def test_chat_id_filter_excludes_rows_without_chat_id(
        self, channel: WebSocketChannel
    ) -> None:
        buf = get_event_buffer()
        # Row without a chat_id (legacy / dashboard-only entry).
        buf.publish(level="info", source="port_scan", message="legacy")
        buf.publish(
            level="info",
            source="port_scan",
            message="scoped",
            chat_id="chat-A",
            category="tool_call",
        )
        resp = channel._handle_events_list(_Req("/api/events?chat_id=chat-A"))
        items = _body(resp)["items"]
        assert len(items) == 1
        assert items[0]["message"] == "scoped"

    def test_unknown_chat_id_returns_empty_items(
        self, channel: WebSocketChannel
    ) -> None:
        self._seed_cross_chat()
        resp = channel._handle_events_list(
            _Req("/api/events?chat_id=does-not-exist")
        )
        assert resp.status_code == 200
        assert _body(resp)["items"] == []

    def test_category_filter_single_value(
        self, channel: WebSocketChannel
    ) -> None:
        self._seed_cross_chat()
        resp = channel._handle_events_list(
            _Req("/api/events?category=tool_call")
        )
        items = _body(resp)["items"]
        assert len(items) == 1
        assert items[0]["category"] == "tool_call"
        assert items[0]["chat_id"] == "chat-A"

    def test_category_filter_multi_value(self, channel: WebSocketChannel) -> None:
        self._seed_cross_chat()
        resp = channel._handle_events_list(
            _Req("/api/events?category=tool_call,tool_result")
        )
        items = _body(resp)["items"]
        assert len(items) == 2
        assert {item["category"] for item in items} == {"tool_call", "tool_result"}

    def test_category_unknown_value_returns_empty_not_400(
        self, channel: WebSocketChannel
    ) -> None:
        """Unknown category strings degrade to zero matches, never 400.
        The PRD's degrade-don't-crash principle applies to query filters."""
        self._seed_cross_chat()
        resp = channel._handle_events_list(
            _Req("/api/events?category=bogus")
        )
        assert resp.status_code == 200
        assert _body(resp)["items"] == []

    def test_chat_id_and_category_compose(self, channel: WebSocketChannel) -> None:
        self._seed_cross_chat()
        resp = channel._handle_events_list(
            _Req("/api/events?chat_id=chat-A&category=thought,tool_result")
        )
        items = _body(resp)["items"]
        assert len(items) == 2
        assert {item["category"] for item in items} == {"thought", "tool_result"}
        assert {item["chat_id"] for item in items} == {"chat-A"}

    def test_no_query_params_preserves_legacy_shape(
        self, channel: WebSocketChannel
    ) -> None:
        """Back-compat: a caller without the new query params sees
        exactly the same rows it would have before B7. Entries now carry
        ``chat_id`` / ``category`` keys (may be ``None``) — the legacy
        ``{id, timestamp, level, source, task_id, message}`` set is a
        subset of the new shape."""
        self._seed_cross_chat()
        resp = channel._handle_events_list(_Req("/api/events"))
        items = _body(resp)["items"]
        assert len(items) == 4
        for entry in items:
            assert set(entry.keys()) >= {
                "id",
                "timestamp",
                "level",
                "source",
                "message",
                "task_id",
                "chat_id",
                "category",
            }

    def test_blank_chat_id_behaves_like_absent(
        self, channel: WebSocketChannel
    ) -> None:
        self._seed_cross_chat()
        resp = channel._handle_events_list(_Req("/api/events?chat_id="))
        items = _body(resp)["items"]
        # Blank value → no scoping → every row visible.
        assert len(items) == 4

    def test_blank_category_behaves_like_absent(
        self, channel: WebSocketChannel
    ) -> None:
        self._seed_cross_chat()
        resp = channel._handle_events_list(_Req("/api/events?category="))
        items = _body(resp)["items"]
        assert len(items) == 4


# ---------------------------------------------------------------------------
# B7: broadcast_activity_event mirrors into the EventBuffer.
# ---------------------------------------------------------------------------
class TestActivityEventMirror:
    """``broadcast_activity_event`` must populate the EventBuffer so the
    Trace tab replays history over HTTP without a dedicated WS replay."""

    @pytest.mark.asyncio
    async def test_broadcast_mirrors_into_buffer(
        self, channel: WebSocketChannel
    ) -> None:
        await channel.broadcast_activity_event(
            category="tool_call",
            agent="port_scan",
            step="nmap 10.0.0.1",
            chat_id="chat-X",
        )
        items = get_event_buffer().filter(chat_id="chat-X")
        assert len(items) == 1
        entry = items[0]
        assert entry["category"] == "tool_call"
        assert entry["source"] == "port_scan"
        assert entry["chat_id"] == "chat-X"
        assert "nmap 10.0.0.1" in entry["message"]

    @pytest.mark.asyncio
    async def test_broadcast_mirror_respects_throttle(
        self, channel: WebSocketChannel
    ) -> None:
        """Throttled broadcasts must NOT double-write the buffer — the
        PRD's 1/s cap exists so the replay list doesn't balloon."""
        await channel.broadcast_activity_event(
            category="tool_call",
            agent="port_scan",
            step="first",
            chat_id="chat-Y",
        )
        # Within 1 s window → throttled (returns False, no buffer write).
        await channel.broadcast_activity_event(
            category="tool_call",
            agent="port_scan",
            step="dropped",
            chat_id="chat-Y",
        )
        items = get_event_buffer().filter(chat_id="chat-Y")
        assert len(items) == 1
        assert "first" in items[0]["message"]

    @pytest.mark.asyncio
    async def test_broadcast_mirror_tool_result_uses_ok_level(
        self, channel: WebSocketChannel
    ) -> None:
        await channel.broadcast_activity_event(
            category="tool_result",
            agent="weak_password",
            step="done",
            chat_id="chat-Z",
            duration_ms=123,
        )
        items = get_event_buffer().filter(chat_id="chat-Z")
        assert len(items) == 1
        assert items[0]["level"] == "ok"

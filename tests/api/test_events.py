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

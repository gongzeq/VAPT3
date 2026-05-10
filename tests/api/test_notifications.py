"""Tests for the notification center HTTP endpoints (P2/R1)."""

from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from secbot.channels import notifications as notif_module
from secbot.channels.notifications import (
    DEFAULT_BUFFER_SIZE,
    NotificationQueue,
    get_notification_queue,
    reset_queue,
)
from secbot.channels.websocket import WebSocketChannel


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _isolated_queue(monkeypatch: pytest.MonkeyPatch):
    """Each test starts with a fresh singleton and no env overrides."""
    monkeypatch.delenv("SECBOT_NOTIFICATION_BUFFER_SIZE", raising=False)
    reset_queue()
    try:
        yield
    finally:
        reset_queue()


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
# NotificationQueue unit tests
# ---------------------------------------------------------------------------
class TestNotificationQueueUnit:
    def test_publish_assigns_ulid_and_iso_timestamp(self) -> None:
        q = NotificationQueue(maxlen=10)
        item = q.publish(type="critical_vuln", title="x", body="y", link="/t/1")
        # id is 'n-' + 26-char ULID
        assert item["id"].startswith("n-")
        assert len(item["id"]) == 2 + 26
        # timestamp is ISO-8601 with explicit offset (``+00:00``)
        assert item["created_at"].endswith("+00:00")
        assert item["read"] is False
        assert item["link"] == "/t/1"

    def test_publish_newest_first_order(self) -> None:
        q = NotificationQueue(maxlen=10)
        first = q.publish(type="critical_vuln", title="old")
        second = q.publish(type="scan_failed", title="new")
        snap = q.snapshot()
        assert [entry["id"] for entry in snap] == [second["id"], first["id"]]

    def test_maxlen_evicts_oldest(self) -> None:
        q = NotificationQueue(maxlen=2)
        a = q.publish(type="critical_vuln", title="a")
        b = q.publish(type="critical_vuln", title="b")
        c = q.publish(type="critical_vuln", title="c")
        snap = q.snapshot()
        # ``a`` evicted; newest-first order keeps ``c`` then ``b``.
        ids = [entry["id"] for entry in snap]
        assert ids == [c["id"], b["id"]]
        assert a["id"] not in ids

    def test_env_buffer_size_overrides_constructor(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SECBOT_NOTIFICATION_BUFFER_SIZE", "3")
        q = NotificationQueue(maxlen=99)
        assert q.maxlen == 3

    def test_env_buffer_size_invalid_falls_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SECBOT_NOTIFICATION_BUFFER_SIZE", "abc")
        q = NotificationQueue()
        assert q.maxlen == DEFAULT_BUFFER_SIZE

    def test_env_buffer_size_zero_falls_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SECBOT_NOTIFICATION_BUFFER_SIZE", "0")
        q = NotificationQueue(maxlen=7)
        # Zero is treated as invalid; constructor param wins.
        assert q.maxlen == 7

    def test_mark_read_returns_updated_row(self) -> None:
        q = NotificationQueue()
        item = q.publish(type="critical_vuln", title="x")
        updated = q.mark_read(item["id"])
        assert updated is not None
        assert updated["read"] is True
        # Subsequent call still returns True (idempotent).
        again = q.mark_read(item["id"])
        assert again is not None and again["read"] is True

    def test_mark_read_unknown_id_returns_none(self) -> None:
        q = NotificationQueue()
        assert q.mark_read("n-NOPE") is None

    def test_mark_all_read_counts_only_unread(self) -> None:
        q = NotificationQueue()
        a = q.publish(type="critical_vuln", title="a")
        q.publish(type="scan_failed", title="b")
        q.mark_read(a["id"])
        # Only the remaining unread entry should flip.
        assert q.mark_all_read() == 1
        # Second call is a no-op.
        assert q.mark_all_read() == 0

    def test_unknown_type_does_not_raise(self) -> None:
        q = NotificationQueue()
        # Forward-compat: unknown types are accepted (logged).
        item = q.publish(type="future_kind", title="x")
        assert item["type"] == "future_kind"


# ---------------------------------------------------------------------------
# Singleton accessor tests
# ---------------------------------------------------------------------------
class TestSingleton:
    def test_get_queue_returns_same_instance(self) -> None:
        a = get_notification_queue()
        b = get_notification_queue()
        assert a is b

    def test_reset_queue_drops_singleton(self) -> None:
        a = get_notification_queue()
        reset_queue()
        b = get_notification_queue()
        assert a is not b

    def test_reset_clears_global(self) -> None:
        get_notification_queue()
        assert notif_module._queue is not None
        reset_queue()
        assert notif_module._queue is None


# ---------------------------------------------------------------------------
# HTTP handler tests
# ---------------------------------------------------------------------------
class TestNotificationsList:
    def test_unauthenticated_returns_401(self, channel: WebSocketChannel) -> None:
        resp = channel._handle_notifications_list(_Req("/api/notifications", token=None))
        assert resp.status_code == 401

    def test_empty_queue_returns_zero_totals(self, channel: WebSocketChannel) -> None:
        resp = channel._handle_notifications_list(_Req("/api/notifications"))
        assert resp.status_code == 200
        assert _body(resp) == {
            "items": [],
            "total": 0,
            "limit": 50,
            "offset": 0,
            "unread_count": 0,
        }

    def test_default_list_returns_all_newest_first(
        self, channel: WebSocketChannel
    ) -> None:
        q = get_notification_queue()
        a = q.publish(type="critical_vuln", title="old")
        b = q.publish(type="scan_failed", title="new")
        resp = channel._handle_notifications_list(_Req("/api/notifications"))
        body = _body(resp)
        assert body["total"] == 2
        assert body["unread_count"] == 2
        assert [item["id"] for item in body["items"]] == [b["id"], a["id"]]

    def test_unread_filter_excludes_read_entries(
        self, channel: WebSocketChannel
    ) -> None:
        q = get_notification_queue()
        a = q.publish(type="critical_vuln", title="old")
        b = q.publish(type="scan_failed", title="new")
        q.mark_read(a["id"])
        resp = channel._handle_notifications_list(
            _Req("/api/notifications?unread=1")
        )
        body = _body(resp)
        assert body["total"] == 1
        # ``unread_count`` covers the whole queue, not the filtered view.
        assert body["unread_count"] == 1
        assert [item["id"] for item in body["items"]] == [b["id"]]

    def test_read_only_filter(self, channel: WebSocketChannel) -> None:
        q = get_notification_queue()
        a = q.publish(type="critical_vuln", title="old")
        q.publish(type="scan_failed", title="new")
        q.mark_read(a["id"])
        resp = channel._handle_notifications_list(
            _Req("/api/notifications?unread=0")
        )
        body = _body(resp)
        assert body["total"] == 1
        assert [item["id"] for item in body["items"]] == [a["id"]]

    def test_pagination_echoes_limit_offset(
        self, channel: WebSocketChannel
    ) -> None:
        q = get_notification_queue()
        for i in range(5):
            q.publish(type="critical_vuln", title=f"t{i}")
        resp = channel._handle_notifications_list(
            _Req("/api/notifications?limit=2&offset=1")
        )
        body = _body(resp)
        assert body["limit"] == 2
        assert body["offset"] == 1
        assert body["total"] == 5
        assert len(body["items"]) == 2

    def test_limit_clamped_to_500(self, channel: WebSocketChannel) -> None:
        resp = channel._handle_notifications_list(
            _Req("/api/notifications?limit=9999")
        )
        assert _body(resp)["limit"] == 500

    def test_invalid_limit_returns_400(self, channel: WebSocketChannel) -> None:
        resp = channel._handle_notifications_list(
            _Req("/api/notifications?limit=abc")
        )
        assert resp.status_code == 400


class TestNotificationRead:
    def test_unauthenticated_returns_401(self, channel: WebSocketChannel) -> None:
        resp = channel._handle_notification_read(
            _Req("/api/notifications/n-x/read", token=None), "n-x"
        )
        assert resp.status_code == 401

    def test_unknown_id_returns_404(self, channel: WebSocketChannel) -> None:
        resp = channel._handle_notification_read(
            _Req("/api/notifications/n-missing/read"), "n-missing"
        )
        assert resp.status_code == 404

    def test_flips_read_flag_persistently(self, channel: WebSocketChannel) -> None:
        q = get_notification_queue()
        item = q.publish(type="critical_vuln", title="t")
        resp = channel._handle_notification_read(
            _Req(f"/api/notifications/{item['id']}/read"), item["id"]
        )
        assert resp.status_code == 200
        assert _body(resp) == {"id": item["id"], "read": True}
        # Second call still 200 — idempotent.
        resp2 = channel._handle_notification_read(
            _Req(f"/api/notifications/{item['id']}/read"), item["id"]
        )
        assert resp2.status_code == 200
        # And ``unread_count`` on the list endpoint drops to 0.
        list_resp = channel._handle_notifications_list(_Req("/api/notifications"))
        assert _body(list_resp)["unread_count"] == 0


class TestNotificationsReadAll:
    def test_unauthenticated_returns_401(self, channel: WebSocketChannel) -> None:
        resp = channel._handle_notifications_read_all(
            _Req("/api/notifications/read-all", token=None)
        )
        assert resp.status_code == 401

    def test_empty_queue_returns_zero(self, channel: WebSocketChannel) -> None:
        resp = channel._handle_notifications_read_all(
            _Req("/api/notifications/read-all")
        )
        assert resp.status_code == 200
        assert _body(resp) == {"updated": 0}

    def test_counts_only_unread_rows(self, channel: WebSocketChannel) -> None:
        q = get_notification_queue()
        a = q.publish(type="critical_vuln", title="a")
        q.publish(type="scan_failed", title="b")
        q.publish(type="scan_completed", title="c")
        q.mark_read(a["id"])  # already read
        resp = channel._handle_notifications_read_all(
            _Req("/api/notifications/read-all")
        )
        assert _body(resp) == {"updated": 2}
        # Idempotent.
        resp2 = channel._handle_notifications_read_all(
            _Req("/api/notifications/read-all")
        )
        assert _body(resp2) == {"updated": 0}

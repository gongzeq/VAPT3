"""Unit tests for P1/R2 session search + archive HTTP routes.

Spec: ``05-10-p1-report-session-prompts/prd.md`` §3.3-§3.4. The handlers are
invoked directly (no real socket) so the suite stays fast, mirroring the
pattern used by ``test_websocket_reports_routes.py`` and
``test_websocket_dashboard_routes.py``.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from secbot.channels.websocket import WebSocketChannel
from secbot.session.manager import Session, SessionManager

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _seed(
    workspace: Path,
    keys: list[str],
    *,
    archived_keys: set[str] | None = None,
    titles: dict[str, str] | None = None,
) -> SessionManager:
    """Create multiple sessions under *workspace* with optional archived /
    title metadata. Each session gets one user message ``hi from <key>``."""
    archived_keys = archived_keys or set()
    titles = titles or {}
    sm = SessionManager(workspace)
    for k in keys:
        s = Session(key=k)
        s.add_message("user", f"hi from {k}")
        if k in titles:
            s.metadata["title"] = titles[k]
        if k in archived_keys:
            s.metadata["archived"] = True
        sm.save(s)
    return sm


@pytest.fixture
def channel_factory():
    """Build a WebSocketChannel with a pre-authenticated API token."""
    def _build(session_manager: SessionManager | None = None) -> WebSocketChannel:
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
            session_manager=session_manager,
        )
        ch._api_tokens["live"] = time.monotonic() + 60.0
        return ch
    return _build


class _Req:
    def __init__(self, path: str, *, token: str | None = "live"):
        self.path = path
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}


def _body(resp) -> dict[str, Any]:
    return json.loads(resp.body)


# ---------------------------------------------------------------------------
# /api/sessions (list) — back-compat + R2 extensions
# ---------------------------------------------------------------------------


async def test_sessions_list_unauthenticated_returns_401(
    channel_factory, tmp_path: Path
) -> None:
    sm = _seed(tmp_path, ["websocket:a"])
    channel = channel_factory(sm)
    resp = channel._handle_sessions_list(_Req("/api/sessions", token=None))
    assert resp.status_code == 401


async def test_sessions_list_injects_archived_flag_and_total(
    channel_factory, tmp_path: Path
) -> None:
    """Legacy clients (no query params) still see ``{"sessions": [...]}``;
    each row now carries ``archived`` and the payload gains ``total``."""
    sm = _seed(
        tmp_path,
        ["websocket:a", "websocket:b"],
        archived_keys={"websocket:b"},
    )
    channel = channel_factory(sm)

    resp = channel._handle_sessions_list(_Req("/api/sessions"))
    assert resp.status_code == 200
    body = _body(resp)
    assert body["total"] == 2
    assert body["limit"] == 50
    assert body["offset"] == 0
    archived_by_key = {s["key"]: s["archived"] for s in body["sessions"]}
    assert archived_by_key == {"websocket:a": False, "websocket:b": True}
    # `path` must never leak — same invariant as pre-R2.
    assert all("path" not in s for s in body["sessions"])


async def test_sessions_list_filters_non_websocket_prefix(
    channel_factory, tmp_path: Path
) -> None:
    """CLI / Slack / Lark rows are not surfaced to the webui."""
    sm = _seed(
        tmp_path,
        ["websocket:alpha", "cli:direct", "slack:C1", "lark:oc_1"],
    )
    channel = channel_factory(sm)
    resp = channel._handle_sessions_list(_Req("/api/sessions"))
    keys = {s["key"] for s in _body(resp)["sessions"]}
    assert keys == {"websocket:alpha"}


async def test_sessions_list_archived_filter_zero_returns_active_only(
    channel_factory, tmp_path: Path
) -> None:
    sm = _seed(
        tmp_path,
        ["websocket:a", "websocket:b", "websocket:c"],
        archived_keys={"websocket:b"},
    )
    channel = channel_factory(sm)

    resp = channel._handle_sessions_list(_Req("/api/sessions?archived=0"))
    body = _body(resp)
    keys = {s["key"] for s in body["sessions"]}
    assert keys == {"websocket:a", "websocket:c"}
    assert body["total"] == 2


async def test_sessions_list_archived_filter_one_returns_archived_only(
    channel_factory, tmp_path: Path
) -> None:
    sm = _seed(
        tmp_path,
        ["websocket:a", "websocket:b", "websocket:c"],
        archived_keys={"websocket:b", "websocket:c"},
    )
    channel = channel_factory(sm)

    resp = channel._handle_sessions_list(_Req("/api/sessions?archived=1"))
    body = _body(resp)
    keys = {s["key"] for s in body["sessions"]}
    assert keys == {"websocket:b", "websocket:c"}
    assert body["total"] == 2


async def test_sessions_list_q_matches_title_and_preview(
    channel_factory, tmp_path: Path
) -> None:
    """``q`` does a case-insensitive LIKE across title + preview + key."""
    sm = _seed(
        tmp_path,
        ["websocket:alpha", "websocket:beta", "websocket:gamma"],
        titles={"websocket:alpha": "Compliance monthly", "websocket:beta": "Ad-hoc scan"},
    )
    channel = channel_factory(sm)

    # Title match on alpha.
    resp = channel._handle_sessions_list(_Req("/api/sessions?q=COMPLIANCE"))
    keys = {s["key"] for s in _body(resp)["sessions"]}
    assert keys == {"websocket:alpha"}

    # Preview match on gamma (preview is ``hi from websocket:gamma``).
    resp2 = channel._handle_sessions_list(_Req("/api/sessions?q=gamma"))
    keys2 = {s["key"] for s in _body(resp2)["sessions"]}
    assert keys2 == {"websocket:gamma"}


async def test_sessions_list_pagination_applies_after_filters(
    channel_factory, tmp_path: Path
) -> None:
    sm = _seed(
        tmp_path,
        [f"websocket:s{i:02d}" for i in range(6)],
    )
    channel = channel_factory(sm)

    resp = channel._handle_sessions_list(
        _Req("/api/sessions?limit=2&offset=1")
    )
    body = _body(resp)
    # ``total`` is pre-pagination — all six rows after the archived/q filter.
    assert body["total"] == 6
    assert body["limit"] == 2
    assert body["offset"] == 1
    assert len(body["sessions"]) == 2


async def test_sessions_list_invalid_limit_returns_400(
    channel_factory, tmp_path: Path
) -> None:
    sm = _seed(tmp_path, ["websocket:a"])
    channel = channel_factory(sm)
    resp = channel._handle_sessions_list(
        _Req("/api/sessions?limit=not-a-number")
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# /api/sessions/{key}/archive
# ---------------------------------------------------------------------------


async def test_session_archive_flips_flag_and_persists(
    channel_factory, tmp_path: Path
) -> None:
    sm = _seed(tmp_path, ["websocket:target"])
    channel = channel_factory(sm)

    resp = channel._handle_session_archive(
        _Req("/api/sessions/websocket:target/archive?archived=1"),
        "websocket:target",
    )
    assert resp.status_code == 200
    assert _body(resp) == {"key": "websocket:target", "archived": True}

    # Persisted: re-reading the file shows the flag.
    re_read = sm.read_session_file("websocket:target")
    assert re_read is not None
    assert re_read["metadata"]["archived"] is True

    # And list_sessions surfaces it.
    rows = sm.list_sessions()
    assert next(r for r in rows if r["key"] == "websocket:target")["archived"] is True


async def test_session_archive_default_parameter_is_archive(
    channel_factory, tmp_path: Path
) -> None:
    """Omitting ``?archived=`` archives (the minimal call is the common one)."""
    sm = _seed(tmp_path, ["websocket:bare"])
    channel = channel_factory(sm)
    resp = channel._handle_session_archive(
        _Req("/api/sessions/websocket:bare/archive"),
        "websocket:bare",
    )
    assert resp.status_code == 200
    assert _body(resp)["archived"] is True


async def test_session_archive_zero_unarchives(
    channel_factory, tmp_path: Path
) -> None:
    sm = _seed(
        tmp_path,
        ["websocket:was-archived"],
        archived_keys={"websocket:was-archived"},
    )
    channel = channel_factory(sm)

    resp = channel._handle_session_archive(
        _Req("/api/sessions/websocket:was-archived/archive?archived=0"),
        "websocket:was-archived",
    )
    assert resp.status_code == 200
    assert _body(resp)["archived"] is False


async def test_session_archive_is_idempotent(
    channel_factory, tmp_path: Path
) -> None:
    sm = _seed(
        tmp_path,
        ["websocket:dup"],
        archived_keys={"websocket:dup"},
    )
    channel = channel_factory(sm)

    first = channel._handle_session_archive(
        _Req("/api/sessions/websocket:dup/archive?archived=1"),
        "websocket:dup",
    )
    second = channel._handle_session_archive(
        _Req("/api/sessions/websocket:dup/archive?archived=1"),
        "websocket:dup",
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert _body(first) == _body(second) == {"key": "websocket:dup", "archived": True}


async def test_session_archive_rejects_non_websocket_keys(
    channel_factory, tmp_path: Path
) -> None:
    """Archiving CLI / Slack sessions is out of the webui surface — 404."""
    sm = _seed(tmp_path, ["cli:direct"])
    channel = channel_factory(sm)

    resp = channel._handle_session_archive(
        _Req("/api/sessions/cli:direct/archive?archived=1"),
        "cli:direct",
    )
    assert resp.status_code == 404


async def test_session_archive_missing_session_returns_404(
    channel_factory, tmp_path: Path
) -> None:
    sm = SessionManager(tmp_path)
    channel = channel_factory(sm)

    resp = channel._handle_session_archive(
        _Req("/api/sessions/websocket:ghost/archive?archived=1"),
        "websocket:ghost",
    )
    assert resp.status_code == 404


async def test_session_archive_invalid_archived_param_returns_400(
    channel_factory, tmp_path: Path
) -> None:
    sm = _seed(tmp_path, ["websocket:x"])
    channel = channel_factory(sm)

    resp = channel._handle_session_archive(
        _Req("/api/sessions/websocket:x/archive?archived=maybe"),
        "websocket:x",
    )
    assert resp.status_code == 400


async def test_session_archive_unauthenticated_returns_401(
    channel_factory, tmp_path: Path
) -> None:
    sm = _seed(tmp_path, ["websocket:x"])
    channel = channel_factory(sm)

    resp = channel._handle_session_archive(
        _Req("/api/sessions/websocket:x/archive?archived=1", token=None),
        "websocket:x",
    )
    assert resp.status_code == 401

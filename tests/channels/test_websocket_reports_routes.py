"""Unit tests for the ``/api/reports`` HTTP routes.

Spec: `.trellis/spec/backend/report-meta.md` §5.

Mirrors the in-process pattern used by
``test_websocket_dashboard_routes.py``: the handlers are invoked directly
(no real socket) so the suite stays fast.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from secbot.channels.websocket import WebSocketChannel
from secbot.cmdb import db as cmdb_db
from secbot.cmdb import repo
from secbot.cmdb.models import Base

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded_cmdb(tmp_path: Path):
    await cmdb_db.dispose_engine()
    db_file = tmp_path / "cmdb.sqlite3"
    engine = cmdb_db.init_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield
    finally:
        await cmdb_db.dispose_engine()


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


async def _seed_scan_and_report(
    actor: str,
    *,
    title: str,
    created_at: datetime,
    **kwargs,
):
    async with cmdb_db.get_session() as session:
        scan = await repo.create_scan(session, actor, target=f"t-{title}")
        row = await repo.insert_report_meta(
            session,
            actor,
            scan_id=scan.id,
            title=title,
            type=kwargs.pop("type", "custom"),
            author=kwargs.pop("author", actor),
            status=kwargs.pop("status", "published"),
            critical_count=kwargs.pop("critical_count", 0),
            created_at=created_at,
        )
    return row


# ---------------------------------------------------------------------------
# /api/reports
# ---------------------------------------------------------------------------


async def test_reports_list_empty_db_returns_zero_total(
    channel: WebSocketChannel, seeded_cmdb
) -> None:
    resp = await channel._handle_reports_list(_Req("/api/reports"))
    assert resp.status_code == 200
    body = _body(resp)
    assert body == {"items": [], "total": 0, "limit": 50, "offset": 0}


async def test_reports_list_unauthenticated_returns_401(
    channel: WebSocketChannel, seeded_cmdb
) -> None:
    resp = await channel._handle_reports_list(_Req("/api/reports", token=None))
    assert resp.status_code == 401


async def test_reports_list_filters_range_type_status(
    channel: WebSocketChannel, seeded_cmdb
) -> None:
    now = datetime.now(tz=timezone.utc)
    await _seed_scan_and_report(
        "local", title="recent", created_at=now - timedelta(days=1)
    )
    await _seed_scan_and_report(
        "local", title="old", created_at=now - timedelta(days=40)
    )

    # Default range=30d keeps only the 1-day-old row.
    resp = await channel._handle_reports_list(_Req("/api/reports"))
    body = _body(resp)
    assert body["total"] == 1
    assert [item["title"] for item in body["items"]] == ["recent"]

    # range=all surfaces both.
    resp = await channel._handle_reports_list(_Req("/api/reports?range=all"))
    body = _body(resp)
    assert body["total"] == 2

    # Invalid range -> 400.
    resp = await channel._handle_reports_list(_Req("/api/reports?range=14d"))
    assert resp.status_code == 400


async def test_reports_list_pagination_and_ordering(
    channel: WebSocketChannel, seeded_cmdb
) -> None:
    now = datetime.now(tz=timezone.utc)
    for idx in range(3):
        await _seed_scan_and_report(
            "local",
            title=f"r{idx}",
            created_at=now - timedelta(hours=idx),
        )

    resp = await channel._handle_reports_list(
        _Req("/api/reports?range=all&limit=1&offset=1")
    )
    body = _body(resp)
    assert body["total"] == 3
    assert body["limit"] == 1
    assert body["offset"] == 1
    # Most-recent first → offset 1 is the second-most-recent ("r1").
    assert [i["title"] for i in body["items"]] == ["r1"]


# ---------------------------------------------------------------------------
# /api/reports/{id}
# ---------------------------------------------------------------------------


async def test_report_detail_returns_download_url_and_shape(
    channel: WebSocketChannel, seeded_cmdb
) -> None:
    now = datetime.now(tz=timezone.utc)
    row = await _seed_scan_and_report(
        "local", title="detail-check", created_at=now, critical_count=3
    )

    resp = await channel._handle_report_detail(
        _Req(f"/api/reports/{row.id}"), row.id
    )
    assert resp.status_code == 200
    body = _body(resp)
    assert body["id"] == row.id
    assert body["title"] == "detail-check"
    assert body["critical_count"] == 3
    assert body["download_url"] == f"/api/reports/{row.id}/download"
    # created_at is ISO-8601 with a timezone offset.
    assert "T" in body["created_at"] and (
        body["created_at"].endswith("Z") or "+" in body["created_at"] or "-" in body["created_at"][10:]
    )


async def test_report_detail_missing_returns_404(
    channel: WebSocketChannel, seeded_cmdb
) -> None:
    resp = await channel._handle_report_detail(
        _Req("/api/reports/RPT-2099-0101-999"), "RPT-2099-0101-999"
    )
    assert resp.status_code == 404


async def test_report_detail_unauthenticated_returns_401(
    channel: WebSocketChannel, seeded_cmdb
) -> None:
    resp = await channel._handle_report_detail(
        _Req("/api/reports/RPT-2099-0101-999", token=None),
        "RPT-2099-0101-999",
    )
    assert resp.status_code == 401

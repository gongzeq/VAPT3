"""Unit tests for the Dashboard aggregation + agents runtime HTTP routes.

Spec: ``.trellis/spec/backend/dashboard-aggregation.md``.

These tests exercise handlers in-process (without binding a real socket) to
keep the suite fast. End-to-end routing through ``_dispatch_http`` is already
covered by ``test_websocket_http_routes.py``; here we focus on the payload
shape + business logic of the new handlers.
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
    """Initialise the process-wide CMDB engine against an isolated sqlite file.

    Handlers call :func:`secbot.cmdb.db.get_session` directly, so the engine
    must be rebound for the duration of the test and torn down after.
    """
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
    # Pre-seed a valid bearer token so handlers pass the auth gate.
    ch._api_tokens["live"] = time.monotonic() + 60.0
    return ch


class _Req:
    """Minimal ``WsRequest`` stand-in understood by the handlers.

    Only ``path`` and ``headers`` are inspected; nothing else is touched.
    """

    def __init__(self, path: str, *, token: str | None = "live"):
        self.path = path
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}


def _body(resp) -> dict[str, Any]:
    return json.loads(resp.body)


# ---------------------------------------------------------------------------
# /api/dashboard/summary
# ---------------------------------------------------------------------------


async def test_summary_empty_db_returns_zero_kpis(
    channel: WebSocketChannel, seeded_cmdb
) -> None:
    resp = await channel._handle_dashboard_summary(_Req("/api/dashboard/summary"))
    assert resp.status_code == 200
    body = _body(resp)
    for key in (
        "active_tasks",
        "completed_scans",
        "critical_vuln",
        "asset_total",
        "pending_alerts",
        "agents_online",
    ):
        assert body[key] == {"value": 0, "delta": 0}, key
    assert "generated_at" in body


async def test_summary_unauthenticated_returns_401(
    channel: WebSocketChannel, seeded_cmdb
) -> None:
    resp = await channel._handle_dashboard_summary(
        _Req("/api/dashboard/summary", token=None)
    )
    assert resp.status_code == 401


async def test_summary_pulls_agents_online_from_subagent_manager(
    channel: WebSocketChannel, seeded_cmdb
) -> None:
    fake_mgr = MagicMock()
    fake_mgr._task_statuses = {"t1": object(), "t2": object()}
    channel._subagent_manager = fake_mgr

    resp = await channel._handle_dashboard_summary(_Req("/api/dashboard/summary"))
    body = _body(resp)
    assert body["agents_online"] == {"value": 2, "delta": 0}


# ---------------------------------------------------------------------------
# /api/dashboard/vuln-trend
# ---------------------------------------------------------------------------


async def test_vuln_trend_default_30d_dense_series(
    channel: WebSocketChannel, seeded_cmdb
) -> None:
    resp = await channel._handle_dashboard_vuln_trend(_Req("/api/dashboard/vuln-trend"))
    assert resp.status_code == 200
    body = _body(resp)
    assert body["range"] == "30d"
    names = [s["name"] for s in body["series"]]
    assert names == ["critical", "high", "medium", "low"]
    # Dense pre-fill: every series has 30 points even on empty DB.
    for series in body["series"]:
        assert len(series["data"]) == 30
        assert all(p["count"] == 0 for p in series["data"])


async def test_vuln_trend_rejects_invalid_range_with_400(
    channel: WebSocketChannel, seeded_cmdb
) -> None:
    resp = await channel._handle_dashboard_vuln_trend(
        _Req("/api/dashboard/vuln-trend?range=1y")
    )
    assert resp.status_code == 400


async def test_vuln_trend_7d_shape_and_counts(
    channel: WebSocketChannel, seeded_cmdb
) -> None:
    async with cmdb_db.get_session() as session:
        scan = await repo.create_scan(session, "local", target="10.0.0.1")
        asset = await repo.upsert_asset(
            session, "local", scan_id=scan.id, target="10.0.0.1"
        )
        today = datetime.now(tz=timezone.utc)
        await repo.upsert_vulnerability(
            session,
            "local",
            asset_id=asset.id,
            severity="high",
            category="cve",
            title="t1",
            discovered_by="t",
        )
        # Direct mutation to anchor today (the default ``created_at`` is UTC
        # now, which already falls inside the trailing window).
        _ = today

    resp = await channel._handle_dashboard_vuln_trend(
        _Req("/api/dashboard/vuln-trend?range=7d")
    )
    assert resp.status_code == 200
    body = _body(resp)
    assert body["range"] == "7d"
    high = next(s for s in body["series"] if s["name"] == "high")
    assert len(high["data"]) == 7
    total_high = sum(p["count"] for p in high["data"])
    assert total_high == 1


# ---------------------------------------------------------------------------
# /api/dashboard/vuln-distribution
# ---------------------------------------------------------------------------


async def test_vuln_distribution_empty_db_emits_six_main_buckets(
    channel: WebSocketChannel, seeded_cmdb
) -> None:
    resp = await channel._handle_dashboard_vuln_distribution(
        _Req("/api/dashboard/vuln-distribution")
    )
    assert resp.status_code == 200
    body = _body(resp)
    cats = [b["category"] for b in body["buckets"]]
    assert cats == ["injection", "auth", "xss", "misconfig", "exposure", "other"]
    # Server-side Chinese labels — the webui must not need a dictionary.
    names = {b["category"]: b["name"] for b in body["buckets"]}
    assert names["injection"] == "注入"
    assert names["auth"] == "认证缺陷"
    assert names["other"] == "其他"
    assert all(b["count"] == 0 for b in body["buckets"])


async def test_vuln_distribution_folds_small_cve_weak_password_into_other(
    channel: WebSocketChannel, seeded_cmdb
) -> None:
    async with cmdb_db.get_session() as session:
        scan = await repo.create_scan(session, "local", target="t")
        asset = await repo.upsert_asset(session, "local", scan_id=scan.id, target="t")
        # Below the threshold (5): folds into ``other``.
        await repo.upsert_vulnerability(
            session,
            "local",
            asset_id=asset.id,
            severity="high",
            category="cve",
            title="cve-1",
            discovered_by="t",
        )
        await repo.upsert_vulnerability(
            session,
            "local",
            asset_id=asset.id,
            severity="medium",
            category="weak_password",
            title="wp-1",
            discovered_by="t",
        )

    resp = await channel._handle_dashboard_vuln_distribution(
        _Req("/api/dashboard/vuln-distribution")
    )
    body = _body(resp)
    cats = [b["category"] for b in body["buckets"]]
    # 2 rows → below threshold → cve + weak_password collapse into ``other``.
    assert "cve" not in cats
    assert "weak_password" not in cats
    other_bucket = next(b for b in body["buckets"] if b["category"] == "other")
    assert other_bucket["count"] == 2


async def test_vuln_distribution_emits_cve_and_weak_password_when_threshold_crossed(
    channel: WebSocketChannel, seeded_cmdb
) -> None:
    async with cmdb_db.get_session() as session:
        scan = await repo.create_scan(session, "local", target="t")
        asset = await repo.upsert_asset(session, "local", scan_id=scan.id, target="t")
        for i in range(3):
            await repo.upsert_vulnerability(
                session,
                "local",
                asset_id=asset.id,
                severity="high",
                category="cve",
                title=f"cve-{i}",
                discovered_by="t",
            )
        for i in range(2):
            await repo.upsert_vulnerability(
                session,
                "local",
                asset_id=asset.id,
                severity="medium",
                category="weak_password",
                title=f"wp-{i}",
                discovered_by="t",
            )

    resp = await channel._handle_dashboard_vuln_distribution(
        _Req("/api/dashboard/vuln-distribution")
    )
    body = _body(resp)
    by_cat = {b["category"]: b["count"] for b in body["buckets"]}
    assert by_cat["cve"] == 3
    assert by_cat["weak_password"] == 2
    assert by_cat["other"] == 0


# ---------------------------------------------------------------------------
# /api/dashboard/asset-distribution
# ---------------------------------------------------------------------------


async def test_asset_distribution_empty_db_emits_full_roster(
    channel: WebSocketChannel, seeded_cmdb
) -> None:
    resp = await channel._handle_dashboard_asset_distribution(
        _Req("/api/dashboard/asset-distribution")
    )
    body = _body(resp)
    types = [b["type"] for b in body["buckets"]]
    assert types == ["web_app", "api", "database", "server", "network", "other"]
    names = {b["type"]: b["name"] for b in body["buckets"]}
    assert names["web_app"] == "Web 应用"
    assert names["network"] == "网络设备"
    assert all(b["count"] == 0 for b in body["buckets"])


async def test_asset_distribution_groups_by_tags_type(
    channel: WebSocketChannel, seeded_cmdb
) -> None:
    async with cmdb_db.get_session() as session:
        scan = await repo.create_scan(session, "local", target="t")
        for i, kind in enumerate(["web_app", "web_app", "api", None]):
            tags = {"type": kind} if kind else None
            await repo.upsert_asset(
                session,
                "local",
                scan_id=scan.id,
                target=f"host-{i}",
                tags=tags,
            )

    resp = await channel._handle_dashboard_asset_distribution(
        _Req("/api/dashboard/asset-distribution")
    )
    body = _body(resp)
    by_type = {b["type"]: b["count"] for b in body["buckets"]}
    assert by_type["web_app"] == 2
    assert by_type["api"] == 1
    # NULL ``tags.type`` folds into ``other`` per spec §2.4.
    assert by_type["other"] == 1


# ---------------------------------------------------------------------------
# /api/dashboard/asset-cluster
# ---------------------------------------------------------------------------


async def test_asset_cluster_groups_by_system_and_folds_critical_into_high(
    channel: WebSocketChannel, seeded_cmdb
) -> None:
    async with cmdb_db.get_session() as session:
        scan = await repo.create_scan(session, "local", target="t")
        crm = await repo.upsert_asset(
            session,
            "local",
            scan_id=scan.id,
            target="crm-host",
            tags={"system": "CRM"},
        )
        # Asset with no ``tags.system`` must be silently skipped.
        _orphan = await repo.upsert_asset(
            session, "local", scan_id=scan.id, target="orphan", tags={}
        )
        await repo.upsert_vulnerability(
            session,
            "local",
            asset_id=crm.id,
            severity="critical",
            category="cve",
            title="crit",
            discovered_by="t",
        )
        await repo.upsert_vulnerability(
            session,
            "local",
            asset_id=crm.id,
            severity="high",
            category="cve",
            title="h",
            discovered_by="t",
        )
        await repo.upsert_vulnerability(
            session,
            "local",
            asset_id=crm.id,
            severity="low",
            category="cve",
            title="l",
            discovered_by="t",
        )

    resp = await channel._handle_dashboard_asset_cluster(
        _Req("/api/dashboard/asset-cluster")
    )
    body = _body(resp)
    systems = {c["system"]: c for c in body["clusters"]}
    # Only CRM is reported; ``tags.system=None`` asset is omitted per §2.5.
    assert list(systems.keys()) == ["CRM"]
    crm_cluster = systems["CRM"]
    # ``critical`` folds into ``high`` (1 critical + 1 high = 2).
    assert crm_cluster["high"] == 2
    assert crm_cluster["medium"] == 0
    assert crm_cluster["low"] == 1


# ---------------------------------------------------------------------------
# /api/agents
# ---------------------------------------------------------------------------


async def test_agents_default_shape_no_runtime_fields(
    channel: WebSocketChannel,
) -> None:
    # Use the lazy loader that reads from ``secbot/agents/*.yaml``. These
    # ship with the repo, so ``registry`` will not be empty.
    resp = channel._handle_agents(_Req("/api/agents"))
    assert resp.status_code == 200
    body = _body(resp)
    assert "agents" in body
    for entry in body["agents"]:
        assert set(entry.keys()) == {
            "name",
            "display_name",
            "description",
            "scoped_skills",
        }


async def test_agents_include_status_appends_runtime_fields(
    channel: WebSocketChannel,
) -> None:
    resp = channel._handle_agents(_Req("/api/agents?include_status=true"))
    assert resp.status_code == 200
    body = _body(resp)
    assert body["agents"], "expected at least one expert agent yaml in the repo"
    for entry in body["agents"]:
        assert entry["status"] == "offline"
        assert entry["current_task_id"] is None
        assert entry["progress"] is None
        assert entry["last_heartbeat_at"] is None


async def test_agents_handler_with_injected_empty_registry_returns_empty_list(
    channel: WebSocketChannel,
) -> None:
    from secbot.agents.registry import AgentRegistry

    channel._agent_registry = AgentRegistry()
    resp = channel._handle_agents(_Req("/api/agents"))
    body = _body(resp)
    assert body == {"agents": []}


# ---------------------------------------------------------------------------
# WS broadcast helpers (task_update / blackboard_update)
# ---------------------------------------------------------------------------


async def test_broadcast_task_update_fans_out_to_all_connections(
    channel: WebSocketChannel,
) -> None:
    conn = MagicMock()
    conn.send = AsyncMock()
    channel._conn_chats[conn] = {"chat-a"}
    # No chat_id → global broadcast.
    sent = await channel.broadcast_task_update(
        task_id="TASK-1",
        scan_id="SCAN-1",
        status="running",
        progress=0.42,
        kpi={"discovered_assets": 7},
    )
    assert sent is True
    conn.send.assert_awaited_once()
    frame = json.loads(conn.send.await_args.args[0])
    assert frame["event"] == "task_update"
    assert frame["task_id"] == "TASK-1"
    assert frame["scan_id"] == "SCAN-1"
    assert frame["status"] == "running"
    assert frame["progress"] == 0.42
    assert frame["kpi"] == {"discovered_assets": 7}


async def test_broadcast_task_update_throttles_within_1s_window(
    channel: WebSocketChannel,
) -> None:
    conn = MagicMock()
    conn.send = AsyncMock()
    channel._conn_chats[conn] = {"chat"}
    first = await channel.broadcast_task_update(
        task_id="T", scan_id="S", status="running"
    )
    second = await channel.broadcast_task_update(
        task_id="T", scan_id="S", status="running"
    )
    assert first is True
    # Second emission well within 1s MUST be dropped.
    assert second is False
    assert conn.send.await_count == 1


async def test_broadcast_task_update_throttle_is_per_task_id(
    channel: WebSocketChannel,
) -> None:
    conn = MagicMock()
    conn.send = AsyncMock()
    channel._conn_chats[conn] = {"chat"}
    a = await channel.broadcast_task_update(
        task_id="A", scan_id="S", status="running"
    )
    b = await channel.broadcast_task_update(
        task_id="B", scan_id="S", status="running"
    )
    assert a is True and b is True
    assert conn.send.await_count == 2


async def test_broadcast_blackboard_update_scoped_to_chat_subscribers(
    channel: WebSocketChannel,
) -> None:
    c_target = MagicMock()
    c_target.send = AsyncMock()
    c_other = MagicMock()
    c_other.send = AsyncMock()
    channel._subs["chat-target"] = {c_target}
    channel._subs["chat-other"] = {c_other}
    channel._conn_chats[c_target] = {"chat-target"}
    channel._conn_chats[c_other] = {"chat-other"}

    sent = await channel.broadcast_blackboard_update(
        chat_id="chat-target",
        stats={"discovered_assets": 10, "critical_findings": 2},
    )
    assert sent is True
    c_target.send.assert_awaited_once()
    c_other.send.assert_not_awaited()
    frame = json.loads(c_target.send.await_args.args[0])
    assert frame["event"] == "blackboard_update"
    assert frame["chat_id"] == "chat-target"
    assert frame["stats"] == {"discovered_assets": 10, "critical_findings": 2}


async def test_broadcast_returns_false_without_subscribers(
    channel: WebSocketChannel,
) -> None:
    sent = await channel.broadcast_task_update(
        task_id="T", scan_id="S", status="queued"
    )
    assert sent is False


# Silence an unused-import warning in the ``datetime`` branch above without
# triggering ruff's ``F401``; the symbol is imported for type readers of the
# helpers and may be used by future tests extending the fixture.
_ = timedelta  # type: ignore[assignment]

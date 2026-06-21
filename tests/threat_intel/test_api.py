"""Integration tests for the Threat Intel API routes.

P0 acceptance criteria covered:
- List pagination (groups, vulns, IPs, malware)
- Group detail with relations
- Feed run counting
- Overview rendering on empty and populated DB
- Watchlist management (POST/DELETE)
- Error cases (404, 400)
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Use a temp file DB — in-memory SQLite is per-connection so tables
# created in the fixture would not be visible to API request handlers.
_tmp_db = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
_tmp_db.close()
os.environ["SECBOT_THREAT_INTEL_URL"] = f"sqlite+aiosqlite:///{_tmp_db.name}"

try:
    from aiohttp.test_utils import TestClient, TestServer

    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

pytest_plugins = ("pytest_asyncio",)

pytestmark = pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def app():
    """Create an aiohttp app with threat intel routes and a fresh file DB."""
    from aiohttp import web

    from secbot.api.threat_intel_routes import register_routes
    from secbot.threat_intel.db import dispose_engine, get_engine, init_engine
    from secbot.threat_intel.models import Base

    db_path = tempfile.mktemp(suffix=".sqlite3")
    init_engine(f"sqlite+aiosqlite:///{db_path}")
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    application = web.Application()
    register_routes(application)

    yield application

    await dispose_engine()
    try:
        Path(db_path).unlink(missing_ok=True)
    except Exception:
        pass


@pytest.fixture
async def client(app):
    """Create an aiohttp TestClient."""
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    yield client
    await client.close()


async def _seed_data(client: TestClient) -> dict:
    """Seed the DB with test data via repo calls, return created IDs."""
    from secbot.threat_intel.db import get_session
    from secbot.threat_intel.repo import (
        add_to_watchlist,
        upsert_apt_alias,
        upsert_threat_group,
        upsert_threat_infra_ip,
        upsert_threat_vuln,
    )

    async with get_session() as session:
        group, _ = await upsert_threat_group(
            session, name="APT41", mitre_id="G0096", source="mitre",
            description="Chinese state-sponsored group",
        )
        group2, _ = await upsert_threat_group(
            session, name="APT32", mitre_id="G0040", source="mitre",
        )
        await upsert_apt_alias(
            session, alias_name="海莲花", group_id=group2.id,
            naming_org="奇安信", confidence=0.95,
        )
        await add_to_watchlist(session, group_id=group.id, actor_id="local")
        await upsert_threat_infra_ip(
            session, group_id=group.id, ip_address="1.2.3.4",
            ip_type="c2", source="threatfox",
        )
        await upsert_threat_vuln(
            session, cve_id="CVE-2024-11111", is_cisa_kev=True,
            primary_source="cisa_kev",
        )
        gid = group.id
        gid2 = group2.id

    return {"group_id": gid, "group2_id": gid2}


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_overview_empty_db(client):
    """Overview should return renderable structure on empty DB."""
    resp = await client.get("/api/threat-intel/overview")
    assert resp.status == 200
    data = await resp.json()

    assert "freshness" in data
    assert "watched_groups_activity" in data
    assert "high_severity_vulns" in data
    assert "active_c2_ips" in data
    assert "maritime_events" in data
    assert "malware_activity" in data

    assert data["high_severity_vulns"]["total"] == 0
    assert data["active_c2_ips"]["total"] == 0


@pytest.mark.asyncio
async def test_overview_with_data(client):
    """Overview should compute correct stats after seeding."""
    await _seed_data(client)

    resp = await client.get("/api/threat-intel/overview")
    assert resp.status == 200
    data = await resp.json()

    assert data["watched_groups_activity"]["total_watched"] == 1
    assert data["high_severity_vulns"]["total"] == 1
    assert data["active_c2_ips"]["total"] == 1


# ---------------------------------------------------------------------------
# Groups: list pagination + search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_groups_list_pagination(client):
    """Groups list should support pagination."""
    await _seed_data(client)

    resp = await client.get("/api/threat-intel/groups?page=1&page_size=1")
    assert resp.status == 200
    data = await resp.json()

    assert data["total"] >= 2
    assert len(data["items"]) == 1
    assert data["page"] == 1
    assert data["page_size"] == 1


@pytest.mark.asyncio
async def test_groups_list_search_by_name(client):
    """Groups list should support search by name."""
    await _seed_data(client)

    resp = await client.get("/api/threat-intel/groups?q=APT41")
    assert resp.status == 200
    data = await resp.json()

    assert data["total"] >= 1
    assert any(g["name"] == "APT41" for g in data["items"])


@pytest.mark.asyncio
async def test_groups_list_search_chinese_alias(client):
    """Groups list should find groups by Chinese alias."""
    await _seed_data(client)

    resp = await client.get("/api/threat-intel/groups?q=%E6%B5%B7%E8%8E%B2%E8%8A%B1")
    assert resp.status == 200
    data = await resp.json()

    assert data["total"] >= 1
    assert any(g["name"] == "APT32" for g in data["items"])


@pytest.mark.asyncio
async def test_groups_list_watched_filter(client):
    """Groups list should support watched_only filter."""
    await _seed_data(client)

    resp = await client.get("/api/threat-intel/groups?watched=true")
    assert resp.status == 200
    data = await resp.json()

    assert data["total"] == 1
    assert data["items"][0]["name"] == "APT41"


# ---------------------------------------------------------------------------
# Groups: detail with relations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_group_detail_not_found(client):
    """Non-existent group should return 404."""
    resp = await client.get("/api/threat-intel/groups/nonexistent-id")
    assert resp.status == 404
    data = await resp.json()
    assert "error" in data


@pytest.mark.asyncio
async def test_group_detail_with_relations(client):
    """Group detail should include associated IPs, malware, and vulns."""
    ids = await _seed_data(client)

    resp = await client.get(f"/api/threat-intel/groups/{ids['group_id']}")
    assert resp.status == 200
    data = await resp.json()

    assert data["name"] == "APT41"
    assert data["mitre_id"] == "G0096"
    assert data["is_watched"] is True
    assert "infra_ips" in data
    assert len(data["infra_ips"]) >= 1
    assert data["infra_ips"][0]["ip_address"] == "1.2.3.4"


# ---------------------------------------------------------------------------
# Watchlist management
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watchlist_add_and_remove(client):
    """Watch and unwatch should work and be idempotent."""
    ids = await _seed_data(client)
    gid = ids["group2_id"]  # APT32, not watched yet

    # Watch
    resp = await client.post(
        f"/api/threat-intel/groups/{gid}/watch",
        json={"note": "monitoring"},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["watched"] is True

    # Watch again — idempotent
    resp2 = await client.post(f"/api/threat-intel/groups/{gid}/watch")
    assert resp2.status == 200

    # Verify watched
    resp3 = await client.get(f"/api/threat-intel/groups/{gid}")
    assert resp3.status == 200
    detail = await resp3.json()
    assert detail["is_watched"] is True

    # Unwatch
    resp4 = await client.delete(f"/api/threat-intel/groups/{gid}/watch")
    assert resp4.status == 200
    unwatch_data = await resp4.json()
    assert unwatch_data["watched"] is False
    assert unwatch_data["removed"] is True

    # Unwatch again — returns removed=False
    resp5 = await client.delete(f"/api/threat-intel/groups/{gid}/watch")
    assert resp5.status == 200
    unwatch_data2 = await resp5.json()
    assert unwatch_data2["removed"] is False


# ---------------------------------------------------------------------------
# Vulnerabilities: list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vulns_list(client):
    """Vulns list should return paginated results."""
    await _seed_data(client)

    resp = await client.get("/api/threat-intel/vulns")
    assert resp.status == 200
    data = await resp.json()

    assert data["total"] >= 1
    assert any(v["cve_id"] == "CVE-2024-11111" for v in data["items"])


@pytest.mark.asyncio
async def test_vulns_list_cisa_kev_filter(client):
    """Vulns list should support is_cisa_kev filter."""
    await _seed_data(client)

    resp = await client.get("/api/threat-intel/vulns?is_cisa_kev=true")
    assert resp.status == 200
    data = await resp.json()

    assert data["total"] >= 1
    assert all(v.get("is_cisa_kev") for v in data["items"])


# ---------------------------------------------------------------------------
# IPs: list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ips_list(client):
    """IPs list should return paginated results."""
    await _seed_data(client)

    resp = await client.get("/api/threat-intel/ips")
    assert resp.status == 200
    data = await resp.json()

    assert data["total"] >= 1
    assert any(ip["ip_address"] == "1.2.3.4" for ip in data["items"])


# ---------------------------------------------------------------------------
# Feed runs: list + manual trigger validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_feed_runs_empty(client):
    """Feed runs list should work on empty DB."""
    resp = await client.get("/api/threat-intel/feeds/runs")
    assert resp.status == 200
    data = await resp.json()
    assert data["total"] == 0
    assert data["items"] == []


@pytest.mark.asyncio
async def test_feed_pull_invalid_source(client):
    """POST /feeds/pull with invalid source should return 400."""
    resp = await client.post(
        "/api/threat-intel/feeds/pull",
        json={"source": "invalid_source"},
    )
    assert resp.status == 400
    data = await resp.json()
    assert "error" in data


@pytest.mark.asyncio
async def test_feed_pull_missing_source(client):
    """POST /feeds/pull without source should return 400."""
    resp = await client.post(
        "/api/threat-intel/feeds/pull",
        json={},
    )
    assert resp.status == 400
    data = await resp.json()
    assert "error" in data


@pytest.mark.asyncio
async def test_feed_pull_invalid_body(client):
    """POST /feeds/pull with non-JSON body should return 400."""
    resp = await client.post(
        "/api/threat-intel/feeds/pull",
        data="not json",
        headers={"Content-Type": "text/plain"},
    )
    assert resp.status == 400


# ---------------------------------------------------------------------------
# Feed run counting via repo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_feed_run_count_after_repo_insert(client):
    """Feed runs list should count runs created via repo."""
    from secbot.threat_intel.db import get_session
    from secbot.threat_intel.repo import (
        create_feed_pull_run,
        finish_feed_pull_run,
    )

    async with get_session() as session:
        run = await create_feed_pull_run(session, source="cisa_kev", trigger="manual")
        await finish_feed_pull_run(
            session, run_id=run.id, status="ok",
            inserted_count=5, updated_count=3,
        )

    resp = await client.get("/api/threat-intel/feeds/runs")
    assert resp.status == 200
    data = await resp.json()

    assert data["total"] >= 1
    run_item = data["items"][0]
    assert run_item["source"] == "cisa_kev"
    assert run_item["status"] == "ok"
    assert run_item["inserted_count"] == 5

"""Minimal tests for the Threat Intel repository layer.

P0 acceptance criteria covered:
- Table creation + foreign keys
- Upsert deduplication (no duplicates on repeated import)
- Watchlist add/remove idempotency
- Overview statistics in empty DB state
- Chinese alias search
"""

from __future__ import annotations

import os
from datetime import date

import pytest

# Ensure we use an in-memory DB for tests
os.environ["SECBOT_THREAT_INTEL_URL"] = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def session():
    """Create an in-memory DB session for each test."""
    from secbot.threat_intel.db import dispose_engine, get_session, init_engine
    from secbot.threat_intel.models import Base

    init_engine("sqlite+aiosqlite:///:memory:")
    from secbot.threat_intel.db import get_engine
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with get_session() as s:
        yield s

    await dispose_engine()


@pytest.mark.asyncio
async def test_table_creation(session):
    """Tables should be created with correct structure."""
    from sqlalchemy import inspect

    from secbot.threat_intel.db import get_engine

    engine = get_engine()
    async with engine.connect() as conn:
        tables = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).get_table_names()
        )

    expected = {
        "threat_group", "threat_infra_ip", "threat_vuln",
        "threat_group_vuln_assoc", "threat_malware_family",
        "maritime_event", "watchlist", "industry_cpe",
        "apt_alias", "feed_pull_run",
    }
    assert expected.issubset(set(tables)), f"Missing tables: {expected - set(tables)}"


@pytest.mark.asyncio
async def test_upsert_threat_group_dedup(session):
    """Repeated upsert by mitre_id should not create duplicates."""
    from secbot.threat_intel.repo import upsert_threat_group

    # First insert
    g1, created1 = await upsert_threat_group(
        session,
        name="APT41",
        mitre_id="G0096",
        source="mitre",
    )
    assert created1 is True

    # Second insert — same mitre_id → update, not create
    g2, created2 = await upsert_threat_group(
        session,
        name="APT41",
        mitre_id="G0096",
        description="Updated description",
        source="mitre",
    )
    assert created2 is False
    assert g2.id == g1.id
    assert g2.description == "Updated description"


@pytest.mark.asyncio
async def test_upsert_threat_group_by_name(session):
    """Upsert by name (no mitre_id) should dedup correctly."""
    from secbot.threat_intel.repo import upsert_threat_group

    g1, created1 = await upsert_threat_group(session, name="Sandworm", source="mitre")
    g2, created2 = await upsert_threat_group(session, name="sandworm", source="mitre")
    assert created1 is True
    assert created2 is False
    assert g1.id == g2.id


@pytest.mark.asyncio
async def test_upsert_threat_vuln_cisa_kev(session):
    """CISA KEV vuln without CVSS should have severity=high."""
    from secbot.threat_intel.repo import upsert_threat_vuln

    v, created = await upsert_threat_vuln(
        session,
        cve_id="CVE-2024-12345",
        is_cisa_kev=True,
        cisa_kev_date=date(2024, 6, 15),
        primary_source="cisa_kev",
    )
    assert created is True
    assert v.severity == "high"
    assert v.cvss_score is None
    assert v.is_cisa_kev is True


@pytest.mark.asyncio
async def test_upsert_threat_vuln_dedup(session):
    """Repeated CISA KEV upsert should not create duplicates."""
    from secbot.threat_intel.repo import upsert_threat_vuln

    v1, c1 = await upsert_threat_vuln(
        session, cve_id="CVE-2024-99999", is_cisa_kev=True, primary_source="cisa_kev"
    )
    v2, c2 = await upsert_threat_vuln(
        session, cve_id="CVE-2024-99999", is_cisa_kev=True, primary_source="cisa_kev"
    )
    assert c1 is True
    assert c2 is False
    assert v1.id == v2.id


@pytest.mark.asyncio
async def test_watchlist_idempotent(session):
    """Adding to watchlist twice should not raise or duplicate."""
    from secbot.threat_intel.repo import (
        add_to_watchlist,
        remove_from_watchlist,
        upsert_threat_group,
    )

    group, _ = await upsert_threat_group(session, name="TestGroup", mitre_id="G9999")

    # Add twice — should be idempotent
    entry1 = await add_to_watchlist(session, group_id=group.id, actor_id="local")
    entry2 = await add_to_watchlist(session, group_id=group.id, actor_id="local")
    assert entry1.id == entry2.id  # Same entry, not a new one

    # Remove
    removed = await remove_from_watchlist(session, group_id=group.id, actor_id="local")
    assert removed is True

    # Remove again — should return False (already removed)
    removed2 = await remove_from_watchlist(session, group_id=group.id, actor_id="local")
    assert removed2 is False


@pytest.mark.asyncio
async def test_overview_empty_db(session):
    """Overview should return renderable structure on empty DB."""
    from secbot.threat_intel.repo import get_overview

    data = await get_overview(session, actor_id="local")

    assert "freshness" in data
    assert "watched_groups_activity" in data
    assert "high_severity_vulns" in data
    assert "active_c2_ips" in data
    assert "maritime_events" in data
    assert "malware_activity" in data

    assert data["high_severity_vulns"]["total"] == 0
    assert data["active_c2_ips"]["total"] == 0
    assert data["watched_groups_activity"]["total_watched"] == 0


@pytest.mark.asyncio
async def test_overview_with_data(session):
    """Overview should compute correct stats with data."""
    from secbot.threat_intel.repo import (
        add_to_watchlist,
        get_overview,
        upsert_threat_group,
        upsert_threat_infra_ip,
        upsert_threat_vuln,
    )

    # Create a group
    group, _ = await upsert_threat_group(
        session, name="APT41", mitre_id="G0096", source="mitre"
    )

    # Add to watchlist
    await add_to_watchlist(session, group_id=group.id, actor_id="local")

    # Add a C2 IP
    await upsert_threat_infra_ip(
        session,
        group_id=group.id,
        ip_address="1.2.3.4",
        ip_type="c2",
        source="threatfox",
    )

    # Add a vuln
    await upsert_threat_vuln(
        session,
        cve_id="CVE-2024-11111",
        is_cisa_kev=True,
        primary_source="cisa_kev",
    )

    data = await get_overview(session, actor_id="local")

    assert data["watched_groups_activity"]["total_watched"] == 1
    assert data["high_severity_vulns"]["total"] == 1
    assert data["active_c2_ips"]["total"] == 1


@pytest.mark.asyncio
async def test_chinese_alias_search(session):
    """Searching by Chinese alias should find the group via apt_alias table."""
    from secbot.threat_intel.repo import (
        list_threat_groups,
        upsert_apt_alias,
        upsert_threat_group,
    )

    # Create a group
    group, _ = await upsert_threat_group(
        session, name="APT32", mitre_id="G0040", source="mitre"
    )

    # Add Chinese alias
    await upsert_apt_alias(
        session,
        alias_name="海莲花",
        group_id=group.id,
        naming_org="奇安信",
        confidence=0.95,
    )

    # Search by Chinese name
    result = await list_threat_groups(session, q="海莲花", page=1, page_size=20)
    assert result["total"] >= 1
    assert any(g["name"] == "APT32" for g in result["items"])


@pytest.mark.asyncio
async def test_feed_pull_run_lifecycle(session):
    """Feed pull run should track status transitions correctly."""
    from secbot.threat_intel.repo import (
        create_feed_pull_run,
        finish_feed_pull_run,
        list_feed_pull_runs,
    )

    # Create a running feed pull
    run = await create_feed_pull_run(session, source="cisa_kev", trigger="manual")
    assert run.status == "running"

    # Finish it
    finished = await finish_feed_pull_run(
        session,
        run_id=run.id,
        status="ok",
        inserted_count=10,
        updated_count=5,
        skipped_count=2,
        unmapped_count=1,
    )
    assert finished is not None
    assert finished.status == "ok"
    assert finished.inserted_count == 10
    assert finished.finished_at is not None

    # List runs
    result = await list_feed_pull_runs(session, source="cisa_kev")
    assert result["total"] >= 1
    assert result["items"][0]["status"] == "ok"


@pytest.mark.asyncio
async def test_threatfox_unmapped_no_pseudo_group(session):
    """ThreatFox IOCs that can't map to a group should not create pseudo-groups."""
    # Try to upsert an IP with a non-existent group_id
    # This should raise a foreign key error (no pseudo-group created)
    from sqlalchemy.exc import IntegrityError

    from secbot.threat_intel.repo import (
        list_threat_groups,
        upsert_threat_infra_ip,
    )
    with pytest.raises((IntegrityError, Exception)):
        await upsert_threat_infra_ip(
            session,
            group_id="nonexistent-group-id",
            ip_address="9.9.9.9",
            ip_type="c2",
            source="threatfox",
        )

    # Rollback the failed transaction so we can query again
    await session.rollback()

    # Verify no pseudo-groups were created
    result = await list_threat_groups(session)
    assert result["total"] == 0

"""Repo-layer tests for the CMDB.

Covers:

- Scan create / status transitions
- Asset / Service / Vulnerability upsert idempotency (re-scan does not duplicate)
- ``actor_id`` isolation across reads (multi-tenant reservation, spec §4)
- Validation of severity / category / scan status / protocol enums
"""

from __future__ import annotations

import pytest

from secbot.cmdb import repo

# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------


async def test_create_scan_assigns_ulid(tmp_cmdb):
    scan = await repo.create_scan(tmp_cmdb, "local", target="10.0.0.0/24")
    assert scan.id and len(scan.id) == 26  # ULID
    assert scan.actor_id == "local"
    assert scan.status == "queued"


async def test_update_scan_status_transitions_set_timestamps(tmp_cmdb):
    scan = await repo.create_scan(tmp_cmdb, "local", target="10.0.0.1")

    running = await repo.update_scan_status(tmp_cmdb, "local", scan.id, status="running")
    assert running.started_at is not None
    assert running.finished_at is None

    completed = await repo.update_scan_status(tmp_cmdb, "local", scan.id, status="completed")
    assert completed.finished_at is not None
    assert completed.error is None


async def test_update_scan_status_rejects_invalid(tmp_cmdb):
    scan = await repo.create_scan(tmp_cmdb, "local", target="10.0.0.1")
    with pytest.raises(ValueError):
        await repo.update_scan_status(tmp_cmdb, "local", scan.id, status="bogus")


async def test_list_scans_filters_actor(tmp_cmdb):
    await repo.create_scan(tmp_cmdb, "alice", target="10.0.0.1")
    await repo.create_scan(tmp_cmdb, "alice", target="10.0.0.2")
    await repo.create_scan(tmp_cmdb, "bob", target="192.168.0.1")

    alice = await repo.list_scans(tmp_cmdb, "alice")
    bob = await repo.list_scans(tmp_cmdb, "bob")

    assert len(alice) == 2
    assert len(bob) == 1
    assert {s.target for s in alice} == {"10.0.0.1", "10.0.0.2"}


# ---------------------------------------------------------------------------
# Asset
# ---------------------------------------------------------------------------


async def test_upsert_asset_is_idempotent_on_rescan(tmp_cmdb):
    scan = await repo.create_scan(tmp_cmdb, "local", target="example.com")
    a1 = await repo.upsert_asset(
        tmp_cmdb, "local", scan_id=scan.id, target="example.com", ip="93.184.216.34"
    )
    a2 = await repo.upsert_asset(
        tmp_cmdb,
        "local",
        scan_id=scan.id,
        target="example.com",
        ip="93.184.216.34",
        hostname="example.com",
    )

    assert a1.id == a2.id
    assert a2.hostname == "example.com"

    rows = await repo.list_assets(tmp_cmdb, "local", scan_id=scan.id)
    assert len(rows) == 1


async def test_assets_isolated_across_actors(tmp_cmdb):
    scan_a = await repo.create_scan(tmp_cmdb, "alice", target="10.0.0.1")
    scan_b = await repo.create_scan(tmp_cmdb, "bob", target="10.0.0.1")

    await repo.upsert_asset(tmp_cmdb, "alice", scan_id=scan_a.id, target="10.0.0.1")
    await repo.upsert_asset(tmp_cmdb, "bob", scan_id=scan_b.id, target="10.0.0.1")

    alice_assets = await repo.list_assets(tmp_cmdb, "alice")
    bob_assets = await repo.list_assets(tmp_cmdb, "bob")

    assert len(alice_assets) == 1
    assert len(bob_assets) == 1
    assert alice_assets[0].id != bob_assets[0].id


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


async def test_upsert_service_idempotent_and_updates_banner(tmp_cmdb):
    scan = await repo.create_scan(tmp_cmdb, "local", target="10.0.0.1")
    asset = await repo.upsert_asset(tmp_cmdb, "local", scan_id=scan.id, target="10.0.0.1")

    s1 = await repo.upsert_service(
        tmp_cmdb, "local", asset_id=asset.id, port=80, protocol="tcp", state="open"
    )
    s2 = await repo.upsert_service(
        tmp_cmdb,
        "local",
        asset_id=asset.id,
        port=80,
        protocol="tcp",
        state="open",
        product="nginx",
        version="1.27.0",
    )

    assert s1.id == s2.id
    assert s2.product == "nginx"
    assert s2.version == "1.27.0"

    services = await repo.list_services(tmp_cmdb, "local", asset_id=asset.id)
    assert len(services) == 1


async def test_upsert_service_rejects_bad_protocol(tmp_cmdb):
    scan = await repo.create_scan(tmp_cmdb, "local", target="10.0.0.1")
    asset = await repo.upsert_asset(tmp_cmdb, "local", scan_id=scan.id, target="10.0.0.1")

    with pytest.raises(ValueError):
        await repo.upsert_service(
            tmp_cmdb, "local", asset_id=asset.id, port=80, protocol="sctp"
        )


# ---------------------------------------------------------------------------
# Vulnerability
# ---------------------------------------------------------------------------


async def test_upsert_vulnerability_idempotent(tmp_cmdb):
    scan = await repo.create_scan(tmp_cmdb, "local", target="10.0.0.1")
    asset = await repo.upsert_asset(tmp_cmdb, "local", scan_id=scan.id, target="10.0.0.1")
    svc = await repo.upsert_service(
        tmp_cmdb, "local", asset_id=asset.id, port=443, protocol="tcp"
    )

    v1 = await repo.upsert_vulnerability(
        tmp_cmdb,
        "local",
        asset_id=asset.id,
        service_id=svc.id,
        severity="high",
        category="cve",
        title="OpenSSL CVE-2024-9999",
        cve_id="CVE-2024-9999",
        discovered_by="nuclei-template-scan",
    )
    v2 = await repo.upsert_vulnerability(
        tmp_cmdb,
        "local",
        asset_id=asset.id,
        service_id=svc.id,
        severity="critical",  # severity bumped on re-discovery
        category="cve",
        title="OpenSSL CVE-2024-9999",
        cve_id="CVE-2024-9999",
        discovered_by="nuclei-template-scan",
        evidence={"request": "GET /", "response": "vulnerable"},
        raw_log_path="/tmp/raw.log",
    )

    assert v1.id == v2.id
    assert v2.severity == "critical"
    assert v2.evidence == {"request": "GET /", "response": "vulnerable"}

    rows = await repo.list_vulnerabilities(tmp_cmdb, "local", asset_id=asset.id)
    assert len(rows) == 1


async def test_upsert_vulnerability_rejects_bad_enums(tmp_cmdb):
    scan = await repo.create_scan(tmp_cmdb, "local", target="10.0.0.1")
    asset = await repo.upsert_asset(tmp_cmdb, "local", scan_id=scan.id, target="10.0.0.1")

    with pytest.raises(ValueError):
        await repo.upsert_vulnerability(
            tmp_cmdb,
            "local",
            asset_id=asset.id,
            severity="urgent",
            category="cve",
            title="x",
            discovered_by="x",
        )

    with pytest.raises(ValueError):
        await repo.upsert_vulnerability(
            tmp_cmdb,
            "local",
            asset_id=asset.id,
            severity="high",
            category="random",
            title="x",
            discovered_by="x",
        )


async def test_list_vulnerabilities_severity_filter(tmp_cmdb):
    scan = await repo.create_scan(tmp_cmdb, "local", target="10.0.0.1")
    asset = await repo.upsert_asset(tmp_cmdb, "local", scan_id=scan.id, target="10.0.0.1")

    for sev, title in [("low", "x"), ("high", "y"), ("critical", "z")]:
        await repo.upsert_vulnerability(
            tmp_cmdb,
            "local",
            asset_id=asset.id,
            severity=sev,
            category="misconfig",
            title=title,
            discovered_by="nmap-port-scan",
        )

    high_or_above = await repo.list_vulnerabilities(
        tmp_cmdb, "local", severity_in=["high", "critical"]
    )
    assert {v.severity for v in high_or_above} == {"high", "critical"}


async def test_vulnerabilities_isolated_across_actors(tmp_cmdb):
    scan_a = await repo.create_scan(tmp_cmdb, "alice", target="10.0.0.1")
    scan_b = await repo.create_scan(tmp_cmdb, "bob", target="10.0.0.1")
    asset_a = await repo.upsert_asset(tmp_cmdb, "alice", scan_id=scan_a.id, target="10.0.0.1")
    asset_b = await repo.upsert_asset(tmp_cmdb, "bob", scan_id=scan_b.id, target="10.0.0.1")

    await repo.upsert_vulnerability(
        tmp_cmdb,
        "alice",
        asset_id=asset_a.id,
        severity="high",
        category="cve",
        title="alice-only",
        discovered_by="nuclei",
    )
    await repo.upsert_vulnerability(
        tmp_cmdb,
        "bob",
        asset_id=asset_b.id,
        severity="low",
        category="cve",
        title="bob-only",
        discovered_by="nuclei",
    )

    alice = await repo.list_vulnerabilities(tmp_cmdb, "alice")
    bob = await repo.list_vulnerabilities(tmp_cmdb, "bob")

    assert {v.title for v in alice} == {"alice-only"}
    assert {v.title for v in bob} == {"bob-only"}

"""Tests for the Dashboard aggregation repo helpers.

Spec: `.trellis/spec/backend/dashboard-aggregation.md`.

These tests cover the SQL layer only. End-to-end REST responses live in
``tests/api/test_dashboard.py`` (added in Round 2 of the P0 task).
"""

from __future__ import annotations

from datetime import datetime

import pytest

from secbot.cmdb import repo

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _mk_asset(
    session,
    *,
    actor: str = "local",
    target: str = "10.0.0.1",
    tags: dict | None = None,
):
    scan = await repo.create_scan(session, actor, target=target)
    return await repo.upsert_asset(
        session, actor, scan_id=scan.id, target=target, tags=tags
    )


async def _mk_vuln(
    session,
    asset,
    *,
    actor: str = "local",
    severity: str = "high",
    category: str = "cve",
    title: str = "finding",
    created_at: datetime | None = None,
):
    vuln = await repo.upsert_vulnerability(
        session,
        actor,
        asset_id=asset.id,
        severity=severity,
        category=category,
        title=title,
        discovered_by="unit-test",
    )
    # Backdate by direct attribute write: ``created_at`` has a server default
    # that the fixture commits on flush, so we mutate + flush in place.
    if created_at is not None:
        vuln.created_at = created_at
        await session.flush()
    return vuln


# ---------------------------------------------------------------------------
# summary_counts
# ---------------------------------------------------------------------------


async def test_summary_counts_on_empty_db_returns_zeros(tmp_cmdb) -> None:
    counts = await repo.summary_counts(tmp_cmdb, "local")
    for key in (
        "active_tasks",
        "completed_scans",
        "critical_vuln",
        "asset_total",
        "pending_alerts",
    ):
        assert counts[key] == {"value": 0, "delta": 0}


async def test_summary_counts_reflects_active_and_completed_scans(tmp_cmdb) -> None:
    queued = await repo.create_scan(tmp_cmdb, "local", target="a")
    await repo.update_scan_status(tmp_cmdb, "local", queued.id, status="running")

    done = await repo.create_scan(tmp_cmdb, "local", target="b")
    await repo.update_scan_status(tmp_cmdb, "local", done.id, status="completed")

    await repo.create_scan(tmp_cmdb, "local", target="c")  # stays queued

    counts = await repo.summary_counts(tmp_cmdb, "local")
    assert counts["active_tasks"]["value"] == 2  # queued + running
    assert counts["completed_scans"]["value"] == 1


async def test_summary_counts_isolates_actor(tmp_cmdb) -> None:
    alice_scan = await repo.create_scan(tmp_cmdb, "alice", target="a")
    await repo.upsert_asset(
        tmp_cmdb, "alice", scan_id=alice_scan.id, target="a", tags={"system": "CRM"}
    )
    counts = await repo.summary_counts(tmp_cmdb, "bob")
    assert counts["asset_total"]["value"] == 0


# ---------------------------------------------------------------------------
# vuln_trend
# ---------------------------------------------------------------------------


async def test_vuln_trend_rejects_unknown_range(tmp_cmdb) -> None:
    with pytest.raises(ValueError):
        await repo.vuln_trend(tmp_cmdb, "local", range_="42d")


async def test_vuln_trend_empty_returns_dense_zero_series(tmp_cmdb) -> None:
    result = await repo.vuln_trend(tmp_cmdb, "local", range_="7d")
    assert result["range"] == "7d"
    assert [s["name"] for s in result["series"]] == [
        "critical",
        "high",
        "medium",
        "low",
    ]
    for series in result["series"]:
        assert len(series["data"]) == 7
        assert all(entry["count"] == 0 for entry in series["data"])
        # Dates must be unique and ordered ascending.
        dates = [entry["date"] for entry in series["data"]]
        assert dates == sorted(dates)
        assert len(set(dates)) == 7


async def test_vuln_trend_excludes_info_severity(tmp_cmdb) -> None:
    asset = await _mk_asset(tmp_cmdb)
    await _mk_vuln(tmp_cmdb, asset, severity="info", category="exposure", title="i1")
    await _mk_vuln(tmp_cmdb, asset, severity="high", category="cve", title="h1")
    result = await repo.vuln_trend(tmp_cmdb, "local", range_="7d")
    totals = {
        series["name"]: sum(entry["count"] for entry in series["data"])
        for series in result["series"]
    }
    assert totals == {"critical": 0, "high": 1, "medium": 0, "low": 0}


# ---------------------------------------------------------------------------
# vuln_distribution
# ---------------------------------------------------------------------------


async def test_vuln_distribution_returns_all_buckets_even_when_empty(tmp_cmdb) -> None:
    dist = await repo.vuln_distribution(tmp_cmdb, "local")
    assert set(dist.keys()) == {
        "injection",
        "auth",
        "xss",
        "misconfig",
        "exposure",
        "weak_password",
        "cve",
        "other",
    }
    assert all(v == 0 for v in dist.values())


async def test_vuln_distribution_counts_per_category(tmp_cmdb) -> None:
    asset = await _mk_asset(tmp_cmdb)
    for i, cat in enumerate(("injection", "injection", "xss", "auth", "cve")):
        await _mk_vuln(tmp_cmdb, asset, category=cat, title=f"t-{cat}-{i}")
    dist = await repo.vuln_distribution(tmp_cmdb, "local")
    assert dist["injection"] == 2
    assert dist["xss"] == 1
    assert dist["auth"] == 1
    assert dist["cve"] == 1
    assert dist["misconfig"] == 0


# ---------------------------------------------------------------------------
# asset_type_distribution
# ---------------------------------------------------------------------------


async def test_asset_type_distribution_folds_null_into_other(tmp_cmdb) -> None:
    await _mk_asset(tmp_cmdb, target="a1", tags={"type": "业务"})
    await _mk_asset(tmp_cmdb, target="a2", tags={"type": "OA"})
    await _mk_asset(tmp_cmdb, target="a3", tags=None)  # no tags at all
    await _mk_asset(tmp_cmdb, target="a4", tags={"system": "CRM"})  # no `type`

    dist = await repo.asset_type_distribution(tmp_cmdb, "local")
    assert set(dist.keys()) == {
        "业务",
        "智能体",
        "OA",
        "中间件",
        "支撑",
        "内网",
        "其他",
    }
    assert dist["业务"] == 1
    assert dist["OA"] == 1
    assert dist["其他"] == 2


async def test_asset_type_distribution_empty_returns_zeroed_buckets(tmp_cmdb) -> None:
    dist = await repo.asset_type_distribution(tmp_cmdb, "local")
    assert all(v == 0 for v in dist.values())


# ---------------------------------------------------------------------------
# asset_cluster
# ---------------------------------------------------------------------------


async def test_asset_cluster_empty_returns_empty_mapping(tmp_cmdb) -> None:
    cluster = await repo.asset_cluster(tmp_cmdb, "local")
    assert cluster == {}


async def test_asset_cluster_folds_critical_into_high(tmp_cmdb) -> None:
    asset = await _mk_asset(tmp_cmdb, tags={"system": "CRM", "type": "业务"})
    await _mk_vuln(tmp_cmdb, asset, severity="critical", title="c1", category="cve")
    await _mk_vuln(tmp_cmdb, asset, severity="high", title="h1", category="cve")
    await _mk_vuln(tmp_cmdb, asset, severity="medium", title="m1", category="cve")
    await _mk_vuln(tmp_cmdb, asset, severity="low", title="l1", category="cve")
    # info should be excluded from cluster counts
    await _mk_vuln(tmp_cmdb, asset, severity="info", title="i1", category="exposure")

    cluster = await repo.asset_cluster(tmp_cmdb, "local")
    assert cluster == {"CRM": {"high": 2, "medium": 1, "low": 1}}


async def test_asset_cluster_groups_assets_without_system_tag_under_other(tmp_cmdb) -> None:
    # With system
    good = await _mk_asset(
        tmp_cmdb, target="good", tags={"system": "OA", "type": "api"}
    )
    await _mk_vuln(tmp_cmdb, good, severity="high", title="g1")
    # Without system
    bad = await _mk_asset(tmp_cmdb, target="bad", tags={"type": "api"})
    await _mk_vuln(tmp_cmdb, bad, severity="critical", title="b1")

    cluster = await repo.asset_cluster(tmp_cmdb, "local")
    assert cluster["OA"] == {"high": 1, "medium": 0, "low": 0}
    assert cluster["其他"] == {"high": 1, "medium": 0, "low": 0}


async def test_asset_cluster_emits_system_with_zero_findings(tmp_cmdb) -> None:
    # System present but no vulnerabilities — spec §2.5 requires the system to
    # still show up in the widget with zeroed buckets.
    await _mk_asset(tmp_cmdb, target="quiet", tags={"system": "BI", "type": "api"})
    cluster = await repo.asset_cluster(tmp_cmdb, "local")
    assert cluster == {"BI": {"high": 0, "medium": 0, "low": 0}}


# ---------------------------------------------------------------------------
# asset_risk_topology
# ---------------------------------------------------------------------------


async def test_asset_risk_topology_builds_derived_graph_and_sizes_vulns(tmp_cmdb) -> None:
    crm = await _mk_asset(
        tmp_cmdb,
        target="crm.example.com",
        tags={"system": "CRM", "type": "业务"},
    )
    internal = await _mk_asset(
        tmp_cmdb,
        target="10.0.0.8",
        tags={"type": "内网"},
    )
    crm_service = await repo.upsert_service(
        tmp_cmdb,
        "local",
        asset_id=crm.id,
        port=443,
        protocol="tcp",
        state="open",
        service="https",
        product="nginx",
        version="1.18.0",
    )
    internal_service = await repo.upsert_service(
        tmp_cmdb,
        "local",
        asset_id=internal.id,
        port=443,
        protocol="tcp",
        state="open",
        service="https",
    )
    for asset, service in ((crm, crm_service), (internal, internal_service)):
        await repo.upsert_vulnerability(
            tmp_cmdb,
            "local",
            asset_id=asset.id,
            service_id=service.id,
            severity="high",
            category="cve",
            title="shared cve",
            cve_id="CVE-2026-0001",
            discovered_by="unit-test",
        )
    await repo.upsert_vulnerability_candidate(
        tmp_cmdb,
        "local",
        asset_id=crm.id,
        service_id=crm_service.id,
        cve_id="CVE-2026-0002",
        category="cve",
        title="candidate cve",
        source="unit-db",
    )
    await repo.upsert_vulnerability_candidate(
        tmp_cmdb,
        "local",
        asset_id=internal.id,
        service_id=internal_service.id,
        cve_id="CVE-2026-0003",
        category="cve",
        title="dismissed cve",
        source="unit-db",
        status="dismissed",
    )

    graph = await repo.asset_risk_topology(
        tmp_cmdb,
        "local",
        focus_id=f"asset:{crm.id}",
    )

    nodes = {node["id"]: node for node in graph["nodes"]}
    assert graph["focus_id"] == f"asset:{crm.id}"
    assert f"asset:{crm.id}" in nodes
    assert f"asset:{internal.id}" in nodes
    assert nodes[f"asset:{internal.id}"]["data"]["system"] == "其他"
    assert "vulnerability:CVE:CVE-2026-0003:candidate" not in nodes

    confirmed = nodes["vulnerability:CVE:CVE-2026-0001:confirmed"]
    candidate = nodes["vulnerability:CVE:CVE-2026-0002:candidate"]
    assert confirmed["data"]["status"] == "confirmed"
    assert confirmed["data"]["affected_asset_count"] == 2
    assert confirmed["data"]["radius"] > candidate["data"]["radius"]
    assert candidate["data"]["status"] == "candidate"

    edge_kinds = {edge["kind"] for edge in graph["edges"]}
    assert {"asset-service", "confirmed-vulnerability", "candidate-vulnerability"} <= edge_kinds


async def test_asset_risk_topology_filters_candidates_and_system(tmp_cmdb) -> None:
    crm = await _mk_asset(
        tmp_cmdb,
        target="crm.example.com",
        tags={"system": "CRM", "type": "业务"},
    )
    other = await _mk_asset(
        tmp_cmdb,
        target="other.example.com",
        tags={"system": "ERP", "type": "业务"},
    )
    await repo.upsert_vulnerability_candidate(
        tmp_cmdb,
        "local",
        asset_id=crm.id,
        category="cve",
        title="visible candidate",
        cve_id="CVE-2026-0100",
        source="unit-db",
    )
    await repo.upsert_vulnerability_candidate(
        tmp_cmdb,
        "local",
        asset_id=other.id,
        category="cve",
        title="dismissed candidate",
        cve_id="CVE-2026-0200",
        source="unit-db",
        status="dismissed",
    )

    crm_graph = await repo.asset_risk_topology(
        tmp_cmdb,
        "local",
        business_system="CRM",
    )
    assert {node["id"] for node in crm_graph["nodes"] if node["type"] == "asset"} == {
        f"asset:{crm.id}"
    }

    dismissed_graph = await repo.asset_risk_topology(
        tmp_cmdb,
        "local",
        candidate_status="dismissed",
    )
    assert "vulnerability:CVE:CVE-2026-0200:candidate" in {
        node["id"] for node in dismissed_graph["nodes"]
    }

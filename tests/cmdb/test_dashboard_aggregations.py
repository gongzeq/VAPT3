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
    await _mk_asset(tmp_cmdb, target="a1", tags={"type": "web_app"})
    await _mk_asset(tmp_cmdb, target="a2", tags={"type": "api"})
    await _mk_asset(tmp_cmdb, target="a3", tags=None)  # no tags at all
    await _mk_asset(tmp_cmdb, target="a4", tags={"system": "CRM"})  # no `type`

    dist = await repo.asset_type_distribution(tmp_cmdb, "local")
    assert set(dist.keys()) == {
        "web_app",
        "api",
        "database",
        "server",
        "network",
        "other",
    }
    assert dist["web_app"] == 1
    assert dist["api"] == 1
    assert dist["other"] == 2


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
    asset = await _mk_asset(tmp_cmdb, tags={"system": "CRM", "type": "web_app"})
    await _mk_vuln(tmp_cmdb, asset, severity="critical", title="c1", category="cve")
    await _mk_vuln(tmp_cmdb, asset, severity="high", title="h1", category="cve")
    await _mk_vuln(tmp_cmdb, asset, severity="medium", title="m1", category="cve")
    await _mk_vuln(tmp_cmdb, asset, severity="low", title="l1", category="cve")
    # info should be excluded from cluster counts
    await _mk_vuln(tmp_cmdb, asset, severity="info", title="i1", category="exposure")

    cluster = await repo.asset_cluster(tmp_cmdb, "local")
    assert cluster == {"CRM": {"high": 2, "medium": 1, "low": 1}}


async def test_asset_cluster_excludes_assets_without_system_tag(tmp_cmdb) -> None:
    # With system
    good = await _mk_asset(
        tmp_cmdb, target="good", tags={"system": "OA", "type": "api"}
    )
    await _mk_vuln(tmp_cmdb, good, severity="high", title="g1")
    # Without system
    bad = await _mk_asset(tmp_cmdb, target="bad", tags={"type": "api"})
    await _mk_vuln(tmp_cmdb, bad, severity="critical", title="b1")

    cluster = await repo.asset_cluster(tmp_cmdb, "local")
    assert list(cluster.keys()) == ["OA"]
    assert cluster["OA"] == {"high": 1, "medium": 0, "low": 0}


async def test_asset_cluster_emits_system_with_zero_findings(tmp_cmdb) -> None:
    # System present but no vulnerabilities — spec §2.5 requires the system to
    # still show up in the widget with zeroed buckets.
    await _mk_asset(tmp_cmdb, target="quiet", tags={"system": "BI", "type": "api"})
    cluster = await repo.asset_cluster(tmp_cmdb, "local")
    assert cluster == {"BI": {"high": 0, "medium": 0, "low": 0}}

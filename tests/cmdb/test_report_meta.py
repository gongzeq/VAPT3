"""Repo-layer tests for ``report_meta`` (the P1 report persistence block).

Contract: `.trellis/spec/backend/report-meta.md`.

Uses the shared ``tmp_cmdb`` fixture so every test runs against an isolated
SQLite file with the full schema applied (cmdb-schema.md §5).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from secbot.cmdb import repo


async def _make_scan(session, *, actor: str = "local", target: str = "10.0.0.1"):
    scan = await repo.create_scan(session, actor, target=target)
    await session.flush()
    return scan


# ---------------------------------------------------------------------------
# insert_report_meta
# ---------------------------------------------------------------------------


async def test_insert_report_meta_assigns_rpt_id_with_seq(tmp_cmdb):
    scan = await _make_scan(tmp_cmdb)
    fixed = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)

    row1 = await repo.insert_report_meta(
        tmp_cmdb,
        "local",
        scan_id=scan.id,
        title="Monthly",
        type="compliance_monthly",
        author="shan",
        created_at=fixed,
    )
    row2 = await repo.insert_report_meta(
        tmp_cmdb,
        "local",
        scan_id=scan.id,
        title="Follow-up",
        type="vuln_summary",
        author="shan",
        created_at=fixed,
    )

    # Display id matches RPT-YYYY-MMDD-<seq> using the *local* date of
    # ``created_at`` (CI may run in UTC; ``fixed`` is noon UTC so the local
    # date is stable regardless of TZ offsets).
    local_date = fixed.astimezone().date()
    prefix = f"RPT-{local_date.year:04d}-{local_date.month:02d}{local_date.day:02d}"
    assert row1.id == f"{prefix}-001"
    assert row2.id == f"{prefix}-002"
    assert row1.critical_count == 0
    assert row1.status == "published"


async def test_insert_report_meta_rejects_unknown_type_or_status(tmp_cmdb):
    scan = await _make_scan(tmp_cmdb)
    with pytest.raises(ValueError):
        await repo.insert_report_meta(
            tmp_cmdb,
            "local",
            scan_id=scan.id,
            title="Bad",
            type="not_a_type",
            author="shan",
        )
    with pytest.raises(ValueError):
        await repo.insert_report_meta(
            tmp_cmdb,
            "local",
            scan_id=scan.id,
            title="Bad",
            type="custom",
            status="weird",
            author="shan",
        )


# ---------------------------------------------------------------------------
# list_reports
# ---------------------------------------------------------------------------


async def _seed(tmp_cmdb, actor: str, *, title: str, created_at, **kwargs):
    scan = await repo.create_scan(tmp_cmdb, actor, target=f"t-{title}")
    return await repo.insert_report_meta(
        tmp_cmdb,
        actor,
        scan_id=scan.id,
        title=title,
        type=kwargs.pop("type", "custom"),
        author=kwargs.pop("author", actor),
        status=kwargs.pop("status", "published"),
        critical_count=kwargs.pop("critical_count", 0),
        created_at=created_at,
    )


async def test_list_reports_filter_range_and_pagination(tmp_cmdb):
    now = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)
    # Three rows: in-window (2d ago), edge-of-7d (6d ago), out-of-window (40d ago).
    await _seed(tmp_cmdb, "local", title="recent", created_at=now - timedelta(days=2))
    await _seed(tmp_cmdb, "local", title="mid", created_at=now - timedelta(days=6))
    await _seed(tmp_cmdb, "local", title="old", created_at=now - timedelta(days=40))

    rows, total = await repo.list_reports(
        tmp_cmdb, "local", range_="7d", now=now
    )
    titles = [r.title for r in rows]
    assert total == 2
    # Most-recent first (created_at DESC).
    assert titles == ["recent", "mid"]

    rows, total = await repo.list_reports(
        tmp_cmdb, "local", range_="all", limit=1, offset=1, now=now
    )
    assert total == 3
    assert len(rows) == 1
    assert rows[0].title == "mid"  # second of {recent, mid, old}


async def test_list_reports_filter_by_type_and_status(tmp_cmdb):
    now = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)
    await _seed(
        tmp_cmdb, "local", title="m", created_at=now, type="compliance_monthly"
    )
    await _seed(tmp_cmdb, "local", title="v", created_at=now, type="vuln_summary")
    await _seed(
        tmp_cmdb,
        "local",
        title="arch",
        created_at=now,
        type="custom",
        status="archived",
    )

    rows, total = await repo.list_reports(
        tmp_cmdb, "local", range_="all", type="vuln_summary", now=now
    )
    assert total == 1 and rows[0].title == "v"

    rows, total = await repo.list_reports(
        tmp_cmdb, "local", range_="all", status="archived", now=now
    )
    assert total == 1 and rows[0].title == "arch"


async def test_list_reports_scoped_by_actor(tmp_cmdb):
    now = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)
    await _seed(tmp_cmdb, "alice", title="a", created_at=now)
    await _seed(tmp_cmdb, "bob", title="b", created_at=now)

    alice_rows, alice_total = await repo.list_reports(
        tmp_cmdb, "alice", range_="all", now=now
    )
    assert alice_total == 1 and alice_rows[0].title == "a"


async def test_list_reports_rejects_invalid_range(tmp_cmdb):
    with pytest.raises(ValueError):
        await repo.list_reports(tmp_cmdb, "local", range_="14d")


# ---------------------------------------------------------------------------
# get_report / update_report_status
# ---------------------------------------------------------------------------


async def test_get_report_returns_none_when_actor_mismatches(tmp_cmdb):
    now = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)
    row = await _seed(tmp_cmdb, "alice", title="a", created_at=now)
    # bob cannot see alice's report.
    assert await repo.get_report(tmp_cmdb, "bob", row.id) is None
    assert (await repo.get_report(tmp_cmdb, "alice", row.id)).title == "a"


async def test_update_report_status_enforces_transitions(tmp_cmdb):
    now = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)
    row = await _seed(
        tmp_cmdb, "local", title="x", created_at=now, status="editing"
    )

    # Legal: editing -> published
    upd = await repo.update_report_status(
        tmp_cmdb, "local", row.id, new_status="published"
    )
    assert upd.status == "published"

    # Idempotent self-transition.
    upd = await repo.update_report_status(
        tmp_cmdb, "local", row.id, new_status="published"
    )
    assert upd.status == "published"

    # Legal: published -> archived
    upd = await repo.update_report_status(
        tmp_cmdb, "local", row.id, new_status="archived"
    )
    assert upd.status == "archived"

    # Illegal: archived -> editing (not in transition table).
    with pytest.raises(ValueError):
        await repo.update_report_status(
            tmp_cmdb, "local", row.id, new_status="editing"
        )


async def test_update_report_status_missing_row_raises(tmp_cmdb):
    with pytest.raises(LookupError):
        await repo.update_report_status(
            tmp_cmdb, "local", "RPT-2099-0101-999", new_status="published"
        )

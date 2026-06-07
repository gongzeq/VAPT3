"""Tests for log-analysis status derivation and handle/unhandle API (PR1).

Covers:
* ``_derive_status`` — three-state mapping with backward compat
* ``handle`` / ``unhandle`` — idempotent write + undo
* ``history`` / ``latest`` — ``status`` field present and correct
* ``NotificationQueue.mark_read_by_ref`` — cross-ref notification sync
* ``_publish_log_alert_if_needed`` — service-layer notification hook
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from secbot.api import log_analysis_dashboard as lad
from secbot.channels.notifications import NotificationQueue


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the dashboard module at a fresh temporary DB."""
    db = tmp_path / "detection_results.db"
    monkeypatch.setenv("LOG_ANALYSIS_DB_PATH", str(db))
    return db


def _seed_log_analysis(db: Path, rows: list[dict]) -> None:
    """Insert fixture rows into ``log_analysis``."""
    conn = sqlite3.connect(str(db), timeout=2.0)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS log_analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_run_id TEXT, file_name TEXT, log_format TEXT,
            char_count INTEGER, analysis_timestamp TEXT,
            anomaly_count INTEGER, critical_count INTEGER,
            high_count INTEGER, medium_count INTEGER, low_count INTEGER,
            total_entries INTEGER,
            summary TEXT, analysis_json TEXT, created_at TEXT
        )
        """
    )
    for r in rows:
        conn.execute(
            """
            INSERT INTO log_analysis
                (file_name, log_format, char_count, anomaly_count,
                 critical_count, high_count, medium_count, low_count,
                 total_entries, summary, analysis_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                r.get("file_name", "test.log"),
                r.get("log_format", "txt"),
                r.get("char_count", 100),
                r.get("anomaly_count", 0),
                r.get("critical_count", 0),
                r.get("high_count", 0),
                r.get("medium_count", 0),
                r.get("low_count", 0),
                r.get("total_entries", 10),
                r.get("summary", ""),
                json.dumps(r.get("analysis_json", {}), ensure_ascii=False),
                r.get("created_at", "2026-01-01 00:00:00"),
            ),
        )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# _derive_status
# ---------------------------------------------------------------------------

class TestDeriveStatus:
    def test_alert_new_value(self):
        assert lad._derive_status("告警", False) == "alert"

    def test_alert_legacy_urgent(self):
        assert lad._derive_status("紧急处理", False) == "alert"

    def test_normal_new_value(self):
        assert lad._derive_status("正常", False) == "normal"

    def test_normal_legacy_ignore(self):
        assert lad._derive_status("忽略", False) == "normal"

    def test_normal_legacy_watch(self):
        assert lad._derive_status("标记关注", False) == "normal"

    def test_handled_overrides_alert(self):
        assert lad._derive_status("告警", True) == "handled"

    def test_unknown_defaults_normal(self):
        assert lad._derive_status("some_garbage", False) == "normal"

    def test_empty_defaults_normal(self):
        assert lad._derive_status("", False) == "normal"


# ---------------------------------------------------------------------------
# handle / unhandle
# ---------------------------------------------------------------------------

class TestHandleUnhandle:
    def test_handle_creates_row(self, tmp_db: Path):
        _seed_log_analysis(tmp_db, [{"file_name": "a.log"}])
        result = lad.handle(1)
        assert result["ok"] is True
        assert result["log_id"] == 1
        assert "handled_at" in result

    def test_handle_idempotent(self, tmp_db: Path):
        _seed_log_analysis(tmp_db, [{"file_name": "a.log"}])
        r1 = lad.handle(1)
        r2 = lad.handle(1)
        assert r1["ok"] and r2["ok"]

    def test_unhandle_removes_row(self, tmp_db: Path):
        _seed_log_analysis(tmp_db, [{"file_name": "a.log"}])
        lad.handle(1)
        result = lad.unhandle(1)
        assert result["ok"] is True
        assert lad.get_handled_log_ids() == set()

    def test_get_handled_log_ids(self, tmp_db: Path):
        _seed_log_analysis(tmp_db, [
            {"file_name": "a.log"},
            {"file_name": "b.log"},
        ])
        lad.handle(1)
        lad.handle(2)
        assert lad.get_handled_log_ids() == {1, 2}

    def test_handle_no_db(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("LOG_ANALYSIS_DB_PATH", "/nonexistent/path.db")
        result = lad.handle(1)
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# history / latest — status field
# ---------------------------------------------------------------------------

class TestHistoryStatus:
    def test_history_returns_status_normal(self, tmp_db: Path):
        _seed_log_analysis(tmp_db, [
            {"analysis_json": {"suggested_action": "忽略"}},
        ])
        page = lad.history(page=1, page_size=10)
        assert len(page["items"]) == 1
        assert page["items"][0]["status"] == "normal"

    def test_history_returns_status_alert(self, tmp_db: Path):
        _seed_log_analysis(tmp_db, [
            {"analysis_json": {"suggested_action": "告警"}},
        ])
        page = lad.history(page=1, page_size=10)
        assert page["items"][0]["status"] == "alert"

    def test_history_returns_status_handled(self, tmp_db: Path):
        _seed_log_analysis(tmp_db, [
            {"analysis_json": {"suggested_action": "告警"}},
        ])
        lad.handle(1)
        page = lad.history(page=1, page_size=10)
        assert page["items"][0]["status"] == "handled"

    def test_history_legacy_urgent_is_alert(self, tmp_db: Path):
        _seed_log_analysis(tmp_db, [
            {"analysis_json": {"suggested_action": "紧急处理"}},
        ])
        page = lad.history(page=1, page_size=10)
        assert page["items"][0]["status"] == "alert"

    def test_history_legacy_ignore_is_normal(self, tmp_db: Path):
        _seed_log_analysis(tmp_db, [
            {"analysis_json": {"suggested_action": "忽略"}},
        ])
        page = lad.history(page=1, page_size=10)
        assert page["items"][0]["status"] == "normal"

    def test_history_empty_suggested_action_is_normal(self, tmp_db: Path):
        _seed_log_analysis(tmp_db, [
            {"analysis_json": {}},
        ])
        page = lad.history(page=1, page_size=10)
        assert page["items"][0]["status"] == "normal"


class TestLatestStatus:
    def test_latest_returns_status(self, tmp_db: Path):
        _seed_log_analysis(tmp_db, [
            {"analysis_json": {"suggested_action": "告警"}},
        ])
        result = lad.latest()
        assert result["found"] is True
        assert result["status"] == "alert"

    def test_latest_handled_overrides(self, tmp_db: Path):
        _seed_log_analysis(tmp_db, [
            {"analysis_json": {"suggested_action": "告警"}},
        ])
        lad.handle(1)
        result = lad.latest()
        assert result["status"] == "handled"

    def test_latest_no_db(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("LOG_ANALYSIS_DB_PATH", "/nonexistent/path.db")
        result = lad.latest()
        assert result["found"] is False


# ---------------------------------------------------------------------------
# NotificationQueue.mark_read_by_ref
# ---------------------------------------------------------------------------

class TestMarkReadByRef:
    def test_mark_read_by_ref_matches(self):
        q = NotificationQueue(maxlen=50)
        q.publish(
            type="log_alert", title="test",
            ref_type="log_analysis", ref_id=42,
        )
        changed = q.mark_read_by_ref("log_analysis", 42)
        assert changed == 1
        items = q.snapshot()
        assert items[0]["read"] is True

    def test_mark_read_by_ref_no_match(self):
        q = NotificationQueue(maxlen=50)
        q.publish(
            type="log_alert", title="test",
            ref_type="log_analysis", ref_id=42,
        )
        changed = q.mark_read_by_ref("log_analysis", 99)
        assert changed == 0

    def test_mark_read_by_ref_skips_already_read(self):
        q = NotificationQueue(maxlen=50)
        item = q.publish(
            type="log_alert", title="test",
            ref_type="log_analysis", ref_id=42,
        )
        q.mark_read(item["id"])
        changed = q.mark_read_by_ref("log_analysis", 42)
        assert changed == 0

    def test_publish_with_ref_fields(self):
        q = NotificationQueue(maxlen=50)
        item = q.publish(
            type="log_alert", title="test",
            ref_type="log_analysis", ref_id=7,
        )
        assert item["ref_type"] == "log_analysis"
        assert item["ref_id"] == 7


# ---------------------------------------------------------------------------
# _publish_log_alert_if_needed (service layer)
# ---------------------------------------------------------------------------

class TestPublishLogAlert:
    def test_publishes_on_alert(self):
        from secbot.workflow.service import _publish_log_alert_if_needed
        from secbot.workflow.types import StepResult, WorkflowRun

        step3 = StepResult(
            status="success",
            started_at_ms=0,
            finished_at_ms=0,
            duration_ms=0,
            output={
                "parsed": {
                    "suggested_action": "告警",
                    "last_id": 42,
                    "file_name": "auth.log",
                    "anomaly_count": 5,
                }
            },
        )
        run = MagicMock(spec=WorkflowRun)
        run.step_results = {"step3": step3}

        q = NotificationQueue(maxlen=50)
        with patch(
            "secbot.channels.notifications.get_notification_queue",
            return_value=q,
        ):
            _publish_log_alert_if_needed(run)

        items = q.snapshot()
        assert len(items) == 1
        assert items[0]["type"] == "log_alert"
        assert items[0]["ref_type"] == "log_analysis"
        assert items[0]["ref_id"] == 42

    def test_skips_non_alert_action(self):
        from secbot.workflow.service import _publish_log_alert_if_needed
        from secbot.workflow.types import StepResult, WorkflowRun

        step3 = StepResult(
            status="success",
            started_at_ms=0,
            finished_at_ms=0,
            duration_ms=0,
            output={
                "parsed": {
                    "suggested_action": "忽略",
                    "last_id": 1,
                    "file_name": "test.log",
                    "anomaly_count": 0,
                }
            },
        )
        run = MagicMock(spec=WorkflowRun)
        run.step_results = {"step3": step3}

        q = NotificationQueue(maxlen=50)
        with patch(
            "secbot.channels.notifications.get_notification_queue",
            return_value=q,
        ):
            _publish_log_alert_if_needed(run)

        assert len(q.snapshot()) == 0

    def test_skips_failed_step(self):
        from secbot.workflow.service import _publish_log_alert_if_needed
        from secbot.workflow.types import StepResult, WorkflowRun

        step3 = StepResult(
            status="error",
            started_at_ms=0,
            finished_at_ms=0,
            duration_ms=0,
            error="boom",
        )
        run = MagicMock(spec=WorkflowRun)
        run.step_results = {"step3": step3}

        q = NotificationQueue(maxlen=50)
        with patch(
            "secbot.channels.notifications.get_notification_queue",
            return_value=q,
        ):
            _publish_log_alert_if_needed(run)

        assert len(q.snapshot()) == 0

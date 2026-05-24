from __future__ import annotations

import pytest

from secbot.state import (
    BudgetExhausted,
    BudgetExtendDisabled,
    BudgetTracker,
    BudgetView,
    inject_exceeded_message,
)


def test_budget_view_status_healthy_low_exceeded() -> None:
    assert BudgetView(0, 100, 0, 10).status == "HEALTHY"
    assert BudgetView(90, 100, 0, 10).status == "LOW"
    assert BudgetView(10, 100, 10, 10).status == "EXCEEDED"
    assert BudgetView(200, 100, 0, 10, enabled=False).status == "HEALTHY"


def test_tracker_tool_calls_drive_status() -> None:
    now = {"value": 0.0}
    tracker = BudgetTracker(
        "chat-a",
        wall_clock_max_sec=100,
        tool_calls_max=2,
        time_fn=lambda: now["value"],
    )

    tracker.on_tool_call()
    assert tracker.status().tool_calls_used == 1
    assert tracker.status().status == "HEALTHY"
    tracker.on_tool_call()
    assert tracker.status().status == "EXCEEDED"


def test_tracker_wall_clock_drives_status() -> None:
    now = {"value": 0.0}
    tracker = BudgetTracker(
        "chat-a",
        wall_clock_max_sec=100,
        tool_calls_max=10,
        time_fn=lambda: now["value"],
    )

    now["value"] = 91.0
    assert tracker.status().status == "LOW"
    now["value"] = 100.0
    assert tracker.status().status == "EXCEEDED"


def test_grant_share_oversubscribe_rejected_and_reclaim_returns_budget() -> None:
    now = {"value": 0.0}
    tracker = BudgetTracker(
        "chat-a",
        wall_clock_max_sec=100,
        tool_calls_max=10,
        time_fn=lambda: now["value"],
    )

    share = tracker.grant_share("worker-1", 50, 6)
    assert share.worker_id == "worker-1"
    with pytest.raises(BudgetExhausted):
        tracker.grant_share("worker-2", 51, 5)

    tracker.reclaim_share("worker-1")
    share_2 = tracker.grant_share("worker-2", 50, 5)
    assert share_2.max_tool_calls == 5


def test_worker_share_status_counts_worker_and_master() -> None:
    tracker = BudgetTracker("chat-a", wall_clock_max_sec=100, tool_calls_max=10)
    tracker.grant_share("worker-1", 50, 1)

    tracker.on_tool_call(worker_id="worker-1")

    assert tracker.status().tool_calls_used == 1
    assert tracker.status("worker-1").status == "EXCEEDED"


def test_extend_updates_max_and_disabled_raises() -> None:
    tracker = BudgetTracker("chat-a", wall_clock_max_sec=10, tool_calls_max=1)
    tracker.extend(extra_wall_clock_sec=5, extra_tool_calls=2)
    assert tracker.status().wall_clock_max_sec == 15
    assert tracker.status().tool_calls_max == 3

    disabled = BudgetTracker("chat-b", allow_extend=False)
    with pytest.raises(BudgetExtendDisabled):
        disabled.extend(extra_tool_calls=1)


def test_inject_exceeded_message_contains_checkpoint_instructions() -> None:
    msg = inject_exceeded_message(
        BudgetView(901, 900, 61, 60),
        current_phase="Triage",
    )

    assert "[BUDGET_EXCEEDED]" in msg
    assert "findings_summary" in msg
    assert "blockers_summary" in msg
    assert "next_steps" in msg
    assert '"from":"Triage"' in msg
    assert '"to":"Checkpoint"' in msg

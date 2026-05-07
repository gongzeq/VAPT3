"""High-risk confirmation gate tests (spec §6)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from secbot.agents.high_risk import (
    AuditLogger,
    HighRiskGate,
    build_confirmation_payload,
)
from secbot.skills.metadata import SkillMetadata
from secbot.skills.types import SkillContext, SkillResult


def _make_meta(name: str, risk: str) -> SkillMetadata:
    return SkillMetadata(
        name=name,
        display_name=f"{name} display",
        version="1.0.0",
        risk_level=risk,
        category="vuln_scan",
        external_binary="fscan",
        network_egress="required",
        expected_runtime_sec=60,
        summary_size_hint="small",
        skill_dir=Path("/tmp/does-not-exist"),
    )


def _ctx(tmp_path: Path, confirm_fn) -> SkillContext:
    return SkillContext(
        scan_id="scan-xyz",
        scan_dir=tmp_path,
        confirm=confirm_fn,
    )


async def test_low_risk_skill_passes_through(tmp_path: Path):
    calls = []

    async def _run(args, ctx):
        calls.append(args)
        return SkillResult(summary={"ok": True})

    async def _confirm(_p):
        raise AssertionError("should not be called for low-risk skills")

    gate = HighRiskGate()
    meta = _make_meta("nmap-host-discovery", "medium")
    res = await gate.guard(meta, {"target": "x"}, _ctx(tmp_path, _confirm), _run)

    assert res.summary["ok"] is True
    assert calls == [{"target": "x"}]
    assert gate.audit.entries == []


async def test_critical_approve_runs_skill_and_audits(tmp_path: Path):
    async def _run(args, ctx):
        return SkillResult(summary={"ok": True})

    async def _confirm(payload):
        assert payload["skill"] == "hydra-bruteforce"
        assert payload["risk_level"] == "critical"
        return True

    gate = HighRiskGate()
    meta = _make_meta("hydra-bruteforce", "critical")
    res = await gate.guard(meta, {"target": "1.2.3.4"}, _ctx(tmp_path, _confirm), _run)

    assert res.summary == {"ok": True}
    actions = [e["action"] for e in gate.audit.entries]
    assert actions == ["confirm_request", "confirm_approve"]


async def test_critical_deny_short_circuits(tmp_path: Path):
    run_called = False

    async def _run(args, ctx):
        nonlocal run_called
        run_called = True
        return SkillResult(summary={"ok": True})

    async def _confirm(_p):
        return False

    gate = HighRiskGate()
    meta = _make_meta("hydra-bruteforce", "critical")
    res = await gate.guard(meta, {"target": "1.2.3.4"}, _ctx(tmp_path, _confirm), _run)

    assert run_called is False
    assert res.summary.get("user_denied") is True
    assert res.summary["reason"] == "denied"
    assert gate.audit.entries[-1]["action"] == "confirm_deny"


async def test_critical_timeout_short_circuits(tmp_path: Path):
    async def _run(args, ctx):
        raise AssertionError("must not run on timeout")

    async def _confirm(_p):
        await asyncio.sleep(1)  # longer than timeout below
        return True

    gate = HighRiskGate(timeout_sec=1)
    # Force a tight timeout.
    gate.timeout_sec = 0  # pragma: any positive -> we rely on wait_for
    # wait_for with timeout=0 immediately raises TimeoutError.
    meta = _make_meta("fscan-weak-password", "critical")
    res = await gate.guard(meta, {"target": "1.2.3.4"}, _ctx(tmp_path, _confirm), _run)

    assert res.summary["user_denied"] is True
    assert res.summary["reason"] == "confirm_timeout"
    assert gate.audit.entries[-1]["action"] == "confirm_timeout"


async def test_build_confirmation_payload_shape():
    meta = _make_meta("fscan-weak-password", "critical")
    payload = build_confirmation_payload(
        meta,
        {"target": "10.0.0.5", "service": "ssh"},
        "scan-1",
        summary_for_user="Brute-force SSH on 10.0.0.5",
    )
    assert payload["type"] == "high_risk_confirm"
    assert payload["skill"] == "fscan-weak-password"
    assert payload["risk_level"] == "critical"
    assert payload["destructive_action"] is True
    assert payload["scan_id"] == "scan-1"
    assert payload["summary_for_user"] == "Brute-force SSH on 10.0.0.5"
    assert payload["args"] == {"target": "10.0.0.5", "service": "ssh"}


def test_audit_logger_rejects_unknown_action():
    al = AuditLogger()
    with pytest.raises(ValueError):
        al.emit("scan", "x", "confirm_magic")

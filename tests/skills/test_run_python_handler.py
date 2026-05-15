"""Tests for the ``run-python`` skill handler.

Spec coverage:
- skill metadata parses and declares ``risk_level: critical``
  (spec: high-risk-confirmation.md §1–2).
- handler archives the script under ``<scan_dir>/run-python/`` and invokes
  the sandbox with ``python3 -I -B <script>``
  (spec: tool-invocation-safety.md §1, §3.1; skill-contract.md §3).
- happy path / timeout / invalid args / confirm denial.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from secbot.skills.metadata import load_skill_metadata
from secbot.skills.types import (
    InvalidSkillArg,
    SkillResult,
    SkillTimeout,
)

_SKILLS_ROOT = Path(__file__).resolve().parents[2] / "secbot" / "skills"
_RUNNER_TARGET = "secbot.skills._shared.runner"


def test_metadata_is_critical_python3():
    meta = load_skill_metadata(_SKILLS_ROOT / "run-python")
    assert meta.name == "run-python"
    assert meta.risk_level == "critical"
    assert meta.is_critical()
    assert meta.external_binary == "python3"


async def test_run_python_happy(handler_loader, make_ctx, fake_run_command):
    mod = handler_loader("run-python")
    fake_run_command(_RUNNER_TARGET, stdout=b"hello world\n", exit_code=0)
    ctx = make_ctx()

    res = await mod.run({"code": "print('hello world')"}, ctx)

    assert isinstance(res, SkillResult)
    assert res.summary["exit_code"] == 0
    assert res.summary["stdout_tail"] == "hello world\n"
    assert res.summary["bytes"] == len(b"hello world\n")
    assert res.summary["truncated"] is False
    # script archived under scan_dir/run-python/<ts>.py
    script_path = Path(res.summary["script_path"])
    assert script_path.exists()
    assert script_path.parent == ctx.scan_dir / "run-python"
    assert script_path.read_text(encoding="utf-8") == "print('hello world')"
    assert "elapsed_sec" in res.summary


async def test_run_python_truncates_large_stdout(
    handler_loader, make_ctx, fake_run_command
):
    mod = handler_loader("run-python")
    big = b"x" * (20 * 1024)  # > 10KB tail cap
    fake_run_command(_RUNNER_TARGET, stdout=big, exit_code=0)
    ctx = make_ctx()

    res = await mod.run({"code": "print('x' * 20480)"}, ctx)

    assert res.summary["bytes"] == len(big)
    assert res.summary["truncated"] is True
    # stdout_tail equals the last 10 KB
    assert len(res.summary["stdout_tail"].encode("utf-8")) == 10 * 1024


async def test_run_python_nonzero_exit_surfaces_error(
    handler_loader, make_ctx, fake_run_command
):
    mod = handler_loader("run-python")
    fake_run_command(_RUNNER_TARGET, stdout=b"Traceback (last)\n", exit_code=1)
    ctx = make_ctx()

    res = await mod.run({"code": "raise SystemExit(1)"}, ctx)

    assert res.summary["exit_code"] == 1
    # runner.execute attaches a generic error marker when exit_code != 0
    assert res.summary["error"] == "exit=1"


async def test_run_python_timeout_returns_summary(
    handler_loader, make_ctx, fake_run_command
):
    mod = handler_loader("run-python")
    fake_run_command(_RUNNER_TARGET, exc=SkillTimeout("exceeded"))
    ctx = make_ctx()

    res = await mod.run(
        {"code": "while True: pass", "timeout_sec": 2}, ctx
    )

    assert res.summary == {"error": "timeout"}


async def test_run_python_rejects_oversize_code(make_ctx, handler_loader):
    mod = handler_loader("run-python")
    ctx = make_ctx()
    # One byte over the 32 KB limit.
    oversized = "a" * (32 * 1024 + 1)

    with pytest.raises(InvalidSkillArg):
        await mod.run({"code": oversized}, ctx)


async def test_run_python_rejects_empty_code(make_ctx, handler_loader):
    mod = handler_loader("run-python")
    ctx = make_ctx()
    with pytest.raises(InvalidSkillArg):
        await mod.run({"code": ""}, ctx)


async def test_run_python_rejects_out_of_range_timeout(
    make_ctx, handler_loader
):
    mod = handler_loader("run-python")
    ctx = make_ctx()
    with pytest.raises(InvalidSkillArg):
        await mod.run({"code": "print(1)", "timeout_sec": 9999}, ctx)


# --------------------------------------------------------------------------
# HighRiskGate integration — critical skills must block on ctx.confirm
# BEFORE the subprocess is started (spec: high-risk-confirmation.md §2).
# --------------------------------------------------------------------------


async def test_run_python_denial_short_circuits(
    handler_loader, make_ctx, fake_run_command
):
    """A denied confirm must not launch the subprocess at all."""
    from secbot.agents.high_risk import HighRiskGate

    mod = handler_loader("run-python")
    # If the sandbox is reached, surface the violation loudly.
    fake_run_command(
        _RUNNER_TARGET,
        exc=AssertionError("sandbox must not be invoked on denial"),
    )
    meta = load_skill_metadata(_SKILLS_ROOT / "run-python")

    async def _deny(_payload):
        return False

    ctx = make_ctx()
    ctx.confirm = _deny  # type: ignore[assignment]

    gate = HighRiskGate()
    result = await gate.guard(meta, {"code": "print(1)"}, ctx, mod.run)

    assert result.summary == {"user_denied": True, "reason": "denied"}
    # Script should not have been archived either — handler.run never ran.
    assert not (ctx.scan_dir / "run-python").exists()


async def test_run_python_approval_then_executes(
    handler_loader, make_ctx, fake_run_command
):
    """After approval, the same ctx/gate allows the handler to run."""
    from secbot.agents.high_risk import HighRiskGate

    mod = handler_loader("run-python")
    fake_run_command(_RUNNER_TARGET, stdout=b"ok\n", exit_code=0)
    meta = load_skill_metadata(_SKILLS_ROOT / "run-python")

    calls = {"n": 0}

    async def _approve_once(_payload):
        calls["n"] += 1
        return True

    ctx = make_ctx()
    ctx.confirm = _approve_once  # type: ignore[assignment]

    gate = HighRiskGate()
    res1 = await gate.guard(meta, {"code": "print('ok')"}, ctx, mod.run)
    res2 = await gate.guard(meta, {"code": "print('ok')"}, ctx, mod.run)

    assert res1.summary["exit_code"] == 0
    assert res2.summary["exit_code"] == 0
    # Sticky-per-gate: confirm should fire exactly once.
    assert calls["n"] == 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-x", "-vv"]))

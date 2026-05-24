"""Orchestrator prompt renderer tests."""

from __future__ import annotations

from pathlib import Path

from secbot.agent.blackboard import BlackboardSnapshot
from secbot.agents.orchestrator import (
    render_legacy_orchestrator_prompt,
    render_orchestrator_prompt,
)
from secbot.agents.registry import load_agent_registry
from secbot.state.budget import BudgetView

_AGENTS_DIR = Path(__file__).resolve().parents[2] / "secbot" / "agents"


def test_render_contains_all_four_sections():
    reg = load_agent_registry(_AGENTS_DIR)
    rendered = render_orchestrator_prompt(reg)
    assert rendered.startswith("# Role\n")
    assert "\n# Hard rules\n" in rendered
    assert "\n# Available worker presets\n" in rendered
    assert "\n# Current phase\n" in rendered
    assert "\n# Budget\n" in rendered
    assert "\n# Working style\n" in rendered
    # Role sentence must be present verbatim.
    assert "You are secbot" in rendered


def test_render_injects_worker_presets_and_legacy_aliases():
    reg = load_agent_registry(_AGENTS_DIR)
    rendered = render_orchestrator_prompt(reg)
    for preset in ("recon", "crawl", "triage", "report"):
        assert f"`{preset}`" in rendered
    for name in reg.names():
        assert f"`legacy:{name}`" in rendered


def test_render_lists_scoped_skills():
    reg = load_agent_registry(_AGENTS_DIR)
    rendered = render_orchestrator_prompt(reg)
    # Pick any scoped_skill of any agent and ensure it appears.
    agent = next(iter(reg))
    assert agent.scoped_skills[0] in rendered


def test_render_is_deterministic():
    reg = load_agent_registry(_AGENTS_DIR)
    a = render_orchestrator_prompt(reg)
    b = render_orchestrator_prompt(reg)
    assert a == b


def test_hard_rules_are_phase_aware_without_legacy_ordering():
    reg = load_agent_registry(_AGENTS_DIR)
    rendered = render_orchestrator_prompt(reg)
    assert "create_worker" in rendered
    assert "read_blackboard" in rendered
    assert "write_blackboard" in rendered
    assert "phase_transition" in rendered
    assert "message(content=...)" in rendered
    assert "asset_discovery \u2192 port_scan" not in rendered
    assert "natural ordering" not in rendered


def test_budget_low_is_rendered_in_dynamic_section():
    reg = load_agent_registry(_AGENTS_DIR)
    rendered = render_orchestrator_prompt(
        reg,
        budget_view=BudgetView(
            wall_clock_used_sec=810,
            wall_clock_max_sec=900,
            tool_calls_used=10,
            tool_calls_max=60,
        ),
    )

    assert "status:            LOW" in rendered
    assert "9% used" not in rendered


def test_current_phase_uses_blackboard_snapshot():
    reg = load_agent_registry(_AGENTS_DIR)
    snapshot = BlackboardSnapshot(
        scope=None,
        current_phase="Triage",
        findings=[{"title": "x"}],
        open_hypotheses=[{"title": "h"}],
        pending_approvals=[],
        recent_blockers=[],
        recent_milestones=[],
    )

    rendered = render_orchestrator_prompt(reg, blackboard_snapshot=snapshot)

    assert "phase: Triage" in rendered
    assert "findings_count: 1" in rendered
    assert "open_hypotheses_count: 1" in rendered


def test_legacy_bridge_still_available_for_rollback():
    reg = load_agent_registry(_AGENTS_DIR)
    rendered = render_legacy_orchestrator_prompt(reg)
    assert "asset_discovery \u2192 port_scan" in rendered
    assert "# Available expert agents" in rendered


def test_hand_rolled_registry_orders_table_alphabetically(tmp_path: Path):
    # Build a minimal registry with two agents (name order should be sorted).
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "beta.md").write_text("beta prompt", encoding="utf-8")
    (prompts / "alpha.md").write_text("alpha prompt", encoding="utf-8")

    for idx, name in enumerate(["beta", "alpha"]):
        (tmp_path / f"{name}.yaml").write_text(
            f"""\
name: {name}
display_name: {name.title()} Agent
description: {name} description
system_prompt_file: prompts/{name}.md
scoped_skills:
  - skill-{name}-{idx}
legacy_input_schema:
  type: object
output_schema:
  type: object
""",
            encoding="utf-8",
        )

    reg = load_agent_registry(tmp_path)
    rendered = render_orchestrator_prompt(reg)
    alpha_pos = rendered.index("`legacy:alpha`")
    beta_pos = rendered.index("`legacy:beta`")
    assert alpha_pos < beta_pos

"""Orchestrator prompt renderer tests."""

from __future__ import annotations

from pathlib import Path

from secbot.agents.orchestrator import render_orchestrator_prompt
from secbot.agents.registry import load_agent_registry

_AGENTS_DIR = Path(__file__).resolve().parents[2] / "secbot" / "agents"


def test_render_contains_all_sections():
    reg = load_agent_registry(_AGENTS_DIR)
    rendered = render_orchestrator_prompt(reg)
    assert rendered.startswith("# Role\n")
    assert "\n# Hard rules\n" in rendered
    assert "\n# Planning\n" in rendered
    assert "\n# Available expert agents\n" in rendered
    assert "\n# Working style\n" in rendered
    # Role sentence must be present verbatim.
    assert "You are secbot" in rendered


def test_render_injects_expert_agents_from_registry():
    reg = load_agent_registry(_AGENTS_DIR)
    rendered = render_orchestrator_prompt(reg)
    for name in reg.names():
        assert f"`{name}`" in rendered


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


def test_hard_rules_mention_high_risk_confirmation():
    """Hard rules must still contain the high-risk confirmation rule."""
    reg = load_agent_registry(_AGENTS_DIR)
    rendered = render_orchestrator_prompt(reg)
    assert "high-risk confirmation" in rendered


def test_prompt_uses_subagent_lifecycle_tools_not_asset_polling():
    """The orchestrator should wait on subagent lifecycle, not asset deltas."""
    reg = load_agent_registry(_AGENTS_DIR)
    rendered = render_orchestrator_prompt(reg)
    assert "`check_subagents`" in rendered
    assert "`wait_subagent`" in rendered
    assert "never poll `read_assets` to wait for a subagent" in rendered
    assert "If there are no new assets, stop reading assets" in rendered


def test_hard_rules_no_fixed_ordering():
    """Hard rules must NOT contain a fixed natural ordering pipeline."""
    reg = load_agent_registry(_AGENTS_DIR)
    rendered = render_orchestrator_prompt(reg)
    # Extract the Hard rules section (between "# Hard rules" and next "# ")
    hard_rules_start = rendered.index("\n# Hard rules\n")
    hard_rules_end = rendered.index("\n# Planning\n")
    hard_rules = rendered[hard_rules_start:hard_rules_end]
    assert "natural ordering" not in hard_rules
    assert "natural ordering" not in rendered


def test_planning_section_present():
    """The prompt must contain a # Planning section with dynamic planning guidance."""
    reg = load_agent_registry(_AGENTS_DIR)
    rendered = render_orchestrator_prompt(reg)
    assert "\n# Planning\n" in rendered
    # Planning section should mention dynamic decision-making
    planning_start = rendered.index("# Planning\n") + len("# Planning\n")
    planning_end = rendered.index("\n# Available expert agents\n")
    planning = rendered[planning_start:planning_end]
    assert "Dynamically decide" in planning
    assert "write_plan" in planning


def test_agent_descriptions_render_full_multiline():
    """YAML descriptions must be rendered in full (not just first line).
    The routing knowledge that was moved into YAML descriptions should
    appear in the rendered output.
    """
    reg = load_agent_registry(_AGENTS_DIR)
    rendered = render_orchestrator_prompt(reg)
    # vuln_detec description includes routing rules
    assert "ONLY for HTTP/HTTPS endpoints" in rendered
    # vuln_scan description includes sqlmap gate
    assert "sqlmap-detect is ONLY allowed when hypotheses" in rendered
    # report description includes empty-status guidance
    assert "status" in rendered and "empty" in rendered


def test_prompt_requires_auto_report_after_scan():
    """PR2 contract: the orchestrator MUST auto-spawn report after the
    final scan stage via the ``report-html`` skill. This behaviour is
    baked into both Hard rules and Working style sections and we assert
    it explicitly so future edits don't silently drop the guarantee.
    """
    reg = load_agent_registry(_AGENTS_DIR)
    rendered = render_orchestrator_prompt(reg)
    assert "report-html" in rendered
    assert "`report` expert" in rendered


def test_hand_rolled_registry_orders_sections_alphabetically(tmp_path: Path):
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
    alpha_pos = rendered.index("### `alpha`")
    beta_pos = rendered.index("### `beta`")
    assert alpha_pos < beta_pos

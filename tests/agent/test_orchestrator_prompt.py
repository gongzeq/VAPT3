"""Orchestrator prompt renderer tests."""

from __future__ import annotations

from pathlib import Path

from secbot.agents.orchestrator import render_orchestrator_prompt
from secbot.agents.registry import load_agent_registry

_AGENTS_DIR = Path(__file__).resolve().parents[2] / "secbot" / "agents"


def test_render_contains_all_four_sections():
    reg = load_agent_registry(_AGENTS_DIR)
    rendered = render_orchestrator_prompt(reg)
    assert rendered.startswith("# Role\n")
    assert "\n# Hard rules\n" in rendered
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


def test_hard_rules_mention_confirmation_and_ordering():
    reg = load_agent_registry(_AGENTS_DIR)
    rendered = render_orchestrator_prompt(reg)
    assert "high-risk confirmation" in rendered
    assert "asset_discovery" in rendered
    assert "port_scan" in rendered


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
input_schema:
  type: object
output_schema:
  type: object
""",
            encoding="utf-8",
        )

    reg = load_agent_registry(tmp_path)
    rendered = render_orchestrator_prompt(reg)
    alpha_pos = rendered.index("`alpha`")
    beta_pos = rendered.index("`beta`")
    assert alpha_pos < beta_pos

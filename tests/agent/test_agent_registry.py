"""Tests for secbot.agents.registry."""

from __future__ import annotations

from pathlib import Path

import pytest

from secbot.agents.registry import (
    AgentRegistryError,
    load_agent_registry,
)

REPO_AGENTS_DIR = Path(__file__).resolve().parents[2] / "secbot" / "agents"

REAL_SKILL_NAMES = {
    "nmap-host-discovery",
    "fscan-asset-discovery",
    "masscan-discovery",
    "cmdb-add-target",
    "cmdb-list-assets",
    "cmdb-history-query",
    "nmap-port-scan",
    "nmap-service-fingerprint",
    "fscan-port-scan",
    "nuclei-template-scan",
    "fscan-vuln-scan",
    "hydra-bruteforce",
    "fscan-weak-password",
    "report-markdown",
    "report-pdf",
    "report-docx",
}


# ---------------------------------------------------------------------------
# Real registry shipped with the repo
# ---------------------------------------------------------------------------


def test_real_registry_loads_with_skill_set():
    reg = load_agent_registry(REPO_AGENTS_DIR, skill_names=REAL_SKILL_NAMES)
    assert set(reg.names()) == {
        "asset_discovery",
        "port_scan",
        "vuln_scan",
        "weak_password",
        "report",
    }


def test_real_registry_no_skill_shared_across_agents():
    reg = load_agent_registry(REPO_AGENTS_DIR, skill_names=REAL_SKILL_NAMES)
    seen: dict[str, str] = {}
    for spec in reg:
        for skill in spec.scoped_skills:
            assert skill not in seen, f"{skill} appears in {seen[skill]} and {spec.name}"
            seen[skill] = spec.name


def test_real_registry_tool_surface_shape():
    reg = load_agent_registry(REPO_AGENTS_DIR, skill_names=REAL_SKILL_NAMES)
    surfaces = reg.tool_surfaces()
    assert all(s["type"] == "function" for s in surfaces)
    assert {s["function"]["name"] for s in surfaces} == set(reg.names())
    # Names must be sorted (stable prompt assembly)
    names = [s["function"]["name"] for s in surfaces]
    assert names == sorted(names)


def test_real_registry_unknown_skill_aborts():
    with pytest.raises(AgentRegistryError, match="unknown skill"):
        load_agent_registry(REPO_AGENTS_DIR, skill_names={"nmap-host-discovery"})


def test_real_registry_skill_check_skipped_when_none():
    reg = load_agent_registry(REPO_AGENTS_DIR, skill_names=None)
    assert "asset_discovery" in reg


# ---------------------------------------------------------------------------
# Synthetic fixtures: validation failure modes
# ---------------------------------------------------------------------------


def _write_yaml(dir_: Path, name: str, body: str, *, prompt: str = "stub prompt") -> Path:
    (dir_ / "prompts").mkdir(exist_ok=True)
    (dir_ / "prompts" / f"{name}.md").write_text(prompt, encoding="utf-8")
    p = dir_ / f"{name}.yaml"
    p.write_text(body, encoding="utf-8")
    return p


_VALID = """\
name: alpha
display_name: Alpha
description: a description
system_prompt_file: ./prompts/alpha.md
scoped_skills: [skill-x]
input_schema:
  type: object
output_schema:
  type: object
"""


def test_missing_required_field_aborts(tmp_path):
    bad = _VALID.replace("description: a description\n", "")
    _write_yaml(tmp_path, "alpha", bad)
    with pytest.raises(AgentRegistryError, match="missing required field"):
        load_agent_registry(tmp_path)


def test_name_mismatch_filename_aborts(tmp_path):
    body = _VALID.replace("name: alpha", "name: beta")
    _write_yaml(tmp_path, "alpha", body)
    with pytest.raises(AgentRegistryError, match="must equal filename stem"):
        load_agent_registry(tmp_path)


def test_invalid_name_aborts(tmp_path):
    body = _VALID.replace("name: alpha", "name: Alpha-1")
    _write_yaml(tmp_path, "Alpha-1", body)
    with pytest.raises(AgentRegistryError, match="must match"):
        load_agent_registry(tmp_path)


def test_empty_scoped_skills_aborts(tmp_path):
    body = _VALID.replace("scoped_skills: [skill-x]", "scoped_skills: []")
    _write_yaml(tmp_path, "alpha", body)
    with pytest.raises(AgentRegistryError, match="non-empty list"):
        load_agent_registry(tmp_path)


def test_unknown_skill_aborts(tmp_path):
    _write_yaml(tmp_path, "alpha", _VALID)
    with pytest.raises(AgentRegistryError, match="unknown skill"):
        load_agent_registry(tmp_path, skill_names={"other"})


def test_missing_prompt_file_aborts(tmp_path):
    body = _VALID
    p = tmp_path / "alpha.yaml"
    p.write_text(body, encoding="utf-8")
    # do NOT create prompts/alpha.md
    with pytest.raises(AgentRegistryError, match="system_prompt_file not found"):
        load_agent_registry(tmp_path)


def test_invalid_input_schema_aborts(tmp_path):
    body = _VALID.replace(
        "input_schema:\n  type: object",
        "input_schema:\n  type: not-a-real-type",
    )
    _write_yaml(tmp_path, "alpha", body)
    with pytest.raises(AgentRegistryError, match="not a valid JSON Schema"):
        load_agent_registry(tmp_path)


def test_skill_shared_across_agents_aborts(tmp_path):
    _write_yaml(tmp_path, "alpha", _VALID)
    body2 = _VALID.replace("name: alpha", "name: gamma")
    _write_yaml(tmp_path, "gamma", body2)
    with pytest.raises(AgentRegistryError, match="claimed by both"):
        load_agent_registry(tmp_path)


def test_negative_max_iterations_aborts(tmp_path):
    body = _VALID + "max_iterations: 0\n"
    _write_yaml(tmp_path, "alpha", body)
    with pytest.raises(AgentRegistryError, match="positive int"):
        load_agent_registry(tmp_path)

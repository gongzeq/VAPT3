"""Tests for secbot.agents.registry."""

from __future__ import annotations

from pathlib import Path

import pytest

from secbot.agents.registry import (
    AgentRegistryError,
    load_agent_registry,
)

REPO_AGENTS_DIR = Path(__file__).resolve().parents[2] / "secbot" / "agents"
REPO_SKILLS_DIR = Path(__file__).resolve().parents[2] / "secbot" / "skills"

REAL_SKILL_NAMES = {
    # asset_discovery
    "nmap-host-discovery",
    "fscan-asset-discovery",
    "httpx-probe",
    # port_scan
    "nmap-port-scan",
    "nmap-service-fingerprint",
    "fscan-port-scan",
    # vuln_scan
    "nuclei-template-scan",
    "fscan-vuln-scan",
    "ffuf-dir-fuzz",
    "ffuf-vhost-fuzz",
    "sqlmap-detect",
    "sqlmap-dump",
    # weak_password
    "hydra-bruteforce",
    # report
    "report-html",
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
# Availability (PR3): required_binaries / missing_binaries / available
# ---------------------------------------------------------------------------


def test_availability_defaults_empty_when_skills_root_not_given():
    reg = load_agent_registry(REPO_AGENTS_DIR, skill_names=REAL_SKILL_NAMES)
    spec = reg.get("asset_discovery")
    assert spec.required_binaries == ()
    assert spec.missing_binaries == ()
    assert spec.available is True


def test_availability_all_present(monkeypatch):
    # Pretend every binary is on PATH.
    monkeypatch.setattr(
        "secbot.agents.registry.shutil.which", lambda name: f"/usr/bin/{name}"
    )
    reg = load_agent_registry(
        REPO_AGENTS_DIR,
        skill_names=REAL_SKILL_NAMES,
        skills_root=REPO_SKILLS_DIR,
    )
    asset = reg.get("asset_discovery")
    # asset_discovery uses nmap + fscan + httpx
    assert set(asset.required_binaries) == {"nmap", "fscan", "httpx"}
    assert asset.missing_binaries == ()
    assert asset.available is True

    # report-html declares no external_binary -> required stays empty.
    report = reg.get("report")
    assert report.required_binaries == ()
    assert report.missing_binaries == ()
    assert report.available is True


def test_availability_some_missing(monkeypatch):
    # Only nmap exists; everything else is missing.
    def which(name: str):
        return "/usr/bin/nmap" if name == "nmap" else None

    monkeypatch.setattr("secbot.agents.registry.shutil.which", which)
    reg = load_agent_registry(
        REPO_AGENTS_DIR,
        skill_names=REAL_SKILL_NAMES,
        skills_root=REPO_SKILLS_DIR,
    )
    asset = reg.get("asset_discovery")
    assert "fscan" in asset.missing_binaries
    assert "httpx" in asset.missing_binaries
    assert "nmap" not in asset.missing_binaries
    assert asset.available is False

    # weak_password only needs hydra which is missing.
    weak = reg.get("weak_password")
    assert weak.required_binaries == ("hydra",)
    assert weak.missing_binaries == ("hydra",)
    assert weak.available is False


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

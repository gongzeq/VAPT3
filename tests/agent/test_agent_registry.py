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
    # vuln_detec
    "vuln-detec-manual",
    # crawl_web
    "katana-crawl-web",
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
        "crawl_web",
        "weak_password",
        "report",
        "vuln_detec",
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

    crawl = reg.get("crawl_web")
    assert crawl.required_binaries == ("katana",)
    assert crawl.missing_binaries == ()
    assert crawl.available is True


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

    crawl = reg.get("crawl_web")
    assert crawl.required_binaries == ("katana",)
    assert crawl.missing_binaries == ("katana",)
    assert crawl.available is False


def test_skill_binary_overrides_resolve_when_path_missing(monkeypatch, tmp_path):
    """``skill_binary_overrides`` should mark a binary as resolved even when
    ``shutil.which`` says it is missing, mirroring the precedence skill
    handlers already use (``cfg.tools.skill_binaries[bin]`` > PATH).
    """
    # Pretend nothing is on PATH. The override below should still rescue httpx.
    monkeypatch.setattr("secbot.agents.registry.shutil.which", lambda name: None)

    fake_httpx = tmp_path / "httpx"
    fake_httpx.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    reg = load_agent_registry(
        REPO_AGENTS_DIR,
        skill_names=REAL_SKILL_NAMES,
        skills_root=REPO_SKILLS_DIR,
        skill_binary_overrides={"httpx": str(fake_httpx)},
    )
    asset = reg.get("asset_discovery")
    assert "httpx" in asset.required_binaries
    assert "httpx" not in asset.missing_binaries
    # nmap and fscan are still missing — agent stays offline overall, but
    # the override took effect for httpx.
    assert "fscan" in asset.missing_binaries


def test_skill_binary_overrides_ignored_when_path_does_not_exist(monkeypatch):
    """A configured override pointing at a non-existent file MUST NOT
    falsely mark the binary as available.
    """
    monkeypatch.setattr("secbot.agents.registry.shutil.which", lambda name: None)

    reg = load_agent_registry(
        REPO_AGENTS_DIR,
        skill_names=REAL_SKILL_NAMES,
        skills_root=REPO_SKILLS_DIR,
        skill_binary_overrides={"httpx": "/definitely/not/here/httpx"},
    )
    assert "httpx" in reg.get("asset_discovery").missing_binaries


def test_sqlmap_resolved_via_path_binary(monkeypatch):
    """方式一：PATH 上直接装了 ``sqlmap`` 二进制。

    registry 必须把 sqlmap 列入 vuln_scan.required_binaries，并通过
    ``shutil.which("sqlmap")`` 判定为已就绪。
    """
    monkeypatch.setattr(
        "secbot.agents.registry.shutil.which",
        lambda name: f"/usr/local/bin/{name}",
    )
    reg = load_agent_registry(
        REPO_AGENTS_DIR,
        skill_names=REAL_SKILL_NAMES,
        skills_root=REPO_SKILLS_DIR,
    )
    vuln = reg.get("vuln_scan")
    assert "sqlmap" in vuln.required_binaries, (
        "sqlmap-detect/sqlmap-dump 的 external_binary 必须是 sqlmap，"
        "registry 才能感知这两种 SQLMap 技能的真实依赖。"
    )
    assert "sqlmap" not in vuln.missing_binaries


def test_sqlmap_resolved_via_config_override_pointing_at_sqlmap_py(
    monkeypatch, tmp_path
):
    """方式二：通过 ``python3 sqlmap.py`` 间接调用。

    用户在 ``tools.skillBinaries.sqlmap`` 里配置 sqlmap.py 的绝对路径，
    PATH 上没有 sqlmap 二进制。registry 应通过 override + 文件存在判定
    为已就绪，与 handler 中 ``_resolve_sqlmap_binary`` 的解析顺序保持一致。
    """
    # 模拟 PATH 上没有 sqlmap，只有 ffuf/fscan/nuclei 这些常规二进制。
    def which(name: str):
        if name == "sqlmap":
            return None
        return f"/usr/local/bin/{name}"

    monkeypatch.setattr("secbot.agents.registry.shutil.which", which)

    fake_sqlmap_py = tmp_path / "sqlmap.py"
    fake_sqlmap_py.write_text("# fake sqlmap entry script\n", encoding="utf-8")

    reg = load_agent_registry(
        REPO_AGENTS_DIR,
        skill_names=REAL_SKILL_NAMES,
        skills_root=REPO_SKILLS_DIR,
        skill_binary_overrides={"sqlmap": str(fake_sqlmap_py)},
    )
    vuln = reg.get("vuln_scan")
    assert "sqlmap" in vuln.required_binaries
    assert "sqlmap" not in vuln.missing_binaries, (
        "config.tools.skillBinaries.sqlmap 指向了真实存在的 sqlmap.py，"
        "registry 必须视为已就绪（与 handler 保持一致）。"
    )


def test_sqlmap_missing_when_neither_path_nor_override_present(monkeypatch):
    """两种安装方式都没有 → registry 必须把 sqlmap 报告为 missing。"""
    monkeypatch.setattr(
        "secbot.agents.registry.shutil.which",
        lambda name: None if name == "sqlmap" else f"/usr/local/bin/{name}",
    )
    reg = load_agent_registry(
        REPO_AGENTS_DIR,
        skill_names=REAL_SKILL_NAMES,
        skills_root=REPO_SKILLS_DIR,
    )
    vuln = reg.get("vuln_scan")
    assert "sqlmap" in vuln.missing_binaries
    assert vuln.available is False


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


def test_allow_exec_defaults_false(tmp_path):
    _write_yaml(tmp_path, "alpha", _VALID)
    reg = load_agent_registry(tmp_path, skill_names={"skill-x"})
    assert reg.get("alpha").allow_exec is False


def test_allow_exec_parsed_when_true(tmp_path):
    body = _VALID + "allow_exec: true\n"
    _write_yaml(tmp_path, "alpha", body)
    reg = load_agent_registry(tmp_path, skill_names={"skill-x"})
    assert reg.get("alpha").allow_exec is True


def test_invalid_allow_exec_type_aborts(tmp_path):
    body = _VALID + "allow_exec: yesplease\n"
    _write_yaml(tmp_path, "alpha", body)
    with pytest.raises(AgentRegistryError, match="allow_exec.*must be a bool"):
        load_agent_registry(tmp_path, skill_names={"skill-x"})

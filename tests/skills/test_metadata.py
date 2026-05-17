"""SkillMetadata reader tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from secbot.skills.metadata import (
    SkillMetadata,
    SkillMetadataError,
    load_skill_metadata,
    scan_skills,
)

_SKILLS_ROOT = Path(__file__).resolve().parents[2] / "secbot" / "skills"


def test_load_nmap_host_discovery():
    meta = load_skill_metadata(_SKILLS_ROOT / "nmap-host-discovery")
    assert isinstance(meta, SkillMetadata)
    assert meta.name == "nmap-host-discovery"
    assert meta.risk_level == "medium"
    assert meta.external_binary == "nmap"
    assert meta.network_egress == "required"
    assert meta.expected_runtime_sec > 0
    assert not meta.is_critical()


def test_scan_skills_finds_all_secbot_skills():
    skills = scan_skills(_SKILLS_ROOT)
    for required in (
        "nmap-host-discovery",
        "fscan-asset-discovery",
        "nmap-port-scan",
        "fscan-port-scan",
        "nuclei-template-scan",
        "fscan-vuln-scan",
        "katana-crawl-web",
    ):
        assert required in skills, f"missing skill: {required}"


def test_risk_levels_are_valid():
    skills = scan_skills(_SKILLS_ROOT)
    for name, meta in skills.items():
        assert meta.risk_level in {"low", "medium", "high", "critical"}, name


def test_missing_front_matter_rejected(tmp_path: Path):
    skill = tmp_path / "broken"
    skill.mkdir()
    (skill / "SKILL.md").write_text("no front matter here", encoding="utf-8")
    with pytest.raises(SkillMetadataError):
        load_skill_metadata(skill)


def test_bad_risk_level_rejected(tmp_path: Path):
    skill = tmp_path / "badrisk"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        """\
---
name: badrisk
display_name: X
version: 1.0.0
risk_level: nuclear
category: vuln_scan
external_binary: fscan
network_egress: required
expected_runtime_sec: 60
summary_size_hint: small
---
body
""",
        encoding="utf-8",
    )
    with pytest.raises(SkillMetadataError):
        load_skill_metadata(skill)


def test_name_mismatch_rejected(tmp_path: Path):
    skill = tmp_path / "dir-a"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        """\
---
name: dir-b
display_name: X
version: 1.0.0
risk_level: low
category: report
external_binary: null
network_egress: none
expected_runtime_sec: 30
summary_size_hint: small
---
body
""",
        encoding="utf-8",
    )
    with pytest.raises(SkillMetadataError):
        load_skill_metadata(skill)

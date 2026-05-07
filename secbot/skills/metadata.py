"""Skill metadata loader.

Parses the YAML front-matter in ``SKILL.md`` and exposes the fields the
rest of the platform (orchestrator, high-risk gate, loop) needs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

import yaml

_RISK_LEVELS = frozenset({"low", "medium", "high", "critical"})
_NETWORK_POLICIES = frozenset({"required", "optional", "none"})


class SkillMetadataError(Exception):
    """Raised when a skill's SKILL.md front-matter is malformed."""


@dataclass(frozen=True)
class SkillMetadata:
    name: str
    display_name: str
    version: str
    risk_level: str
    category: str
    external_binary: Optional[str]
    network_egress: str
    expected_runtime_sec: int
    summary_size_hint: str
    skill_dir: Path

    def is_critical(self) -> bool:
        return self.risk_level == "critical"


def _split_front_matter(text: str) -> tuple[Mapping[str, Any], str]:
    if not text.startswith("---\n"):
        raise SkillMetadataError("SKILL.md is missing front-matter delimiter")
    try:
        _, raw, body = text.split("---\n", 2)
    except ValueError as exc:
        raise SkillMetadataError("SKILL.md front-matter is not closed by '---'") from exc
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        raise SkillMetadataError(f"front-matter is not valid YAML: {exc}") from exc
    if not isinstance(data, Mapping):
        raise SkillMetadataError("front-matter must be a mapping")
    return data, body


def load_skill_metadata(skill_dir: Path | str) -> SkillMetadata:
    """Parse ``<skill_dir>/SKILL.md`` and return a validated metadata record."""
    base = Path(skill_dir)
    md_path = base / "SKILL.md"
    if not md_path.is_file():
        raise SkillMetadataError(f"{md_path} does not exist")

    data, _body = _split_front_matter(md_path.read_text(encoding="utf-8"))

    def _req(key: str, typ: type) -> Any:
        if key not in data:
            raise SkillMetadataError(f"{md_path}: missing required field '{key}'")
        val = data[key]
        if not isinstance(val, typ):
            raise SkillMetadataError(
                f"{md_path}: field '{key}' must be {typ.__name__}, got {type(val).__name__}"
            )
        return val

    name = _req("name", str)
    if name != base.name:
        raise SkillMetadataError(
            f"{md_path}: name '{name}' must equal directory name '{base.name}'"
        )

    risk = _req("risk_level", str)
    if risk not in _RISK_LEVELS:
        raise SkillMetadataError(
            f"{md_path}: risk_level must be one of {sorted(_RISK_LEVELS)}, got {risk!r}"
        )

    network = _req("network_egress", str)
    if network not in _NETWORK_POLICIES:
        raise SkillMetadataError(
            f"{md_path}: network_egress must be one of {sorted(_NETWORK_POLICIES)}"
        )

    runtime = _req("expected_runtime_sec", int)
    if runtime <= 0:
        raise SkillMetadataError(f"{md_path}: expected_runtime_sec must be > 0")

    summary_size = _req("summary_size_hint", str)
    if summary_size not in {"small", "medium", "large"}:
        raise SkillMetadataError(
            f"{md_path}: summary_size_hint must be small|medium|large"
        )

    return SkillMetadata(
        name=name,
        display_name=_req("display_name", str),
        version=_req("version", str),
        risk_level=risk,
        category=_req("category", str),
        external_binary=data.get("external_binary"),
        network_egress=network,
        expected_runtime_sec=runtime,
        summary_size_hint=summary_size,
        skill_dir=base,
    )


def scan_skills(
    skills_root: Path | str,
    *,
    strict: bool = False,
) -> dict[str, SkillMetadata]:
    """Return ``{name: SkillMetadata}`` for every subdir containing a valid
    secbot SKILL.md.

    When ``strict=False`` (default), directories whose front-matter does not
    satisfy the secbot schema are silently skipped. This preserves the
    ability to keep legacy secbot skills alongside new secbot skills during
    the PR1 renaming window.
    """
    base = Path(skills_root)
    out: dict[str, SkillMetadata] = {}
    if not base.is_dir():
        return out
    for child in sorted(base.iterdir()):
        if not child.is_dir() or child.name.startswith("_"):
            continue
        if not (child / "SKILL.md").is_file():
            continue
        try:
            meta = load_skill_metadata(child)
        except SkillMetadataError:
            if strict:
                raise
            continue
        out[meta.name] = meta
    return out

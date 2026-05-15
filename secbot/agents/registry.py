"""Expert agent registry: YAML loader + validation + tool-surface generator.

Spec: `.trellis/spec/backend/agent-registry-contract.md`.

Failure mode: ANY validation error during ``load_agent_registry`` aborts startup
with :class:`AgentRegistryError`. There is no partial registration.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")

REQUIRED_FIELDS = (
    "name",
    "display_name",
    "description",
    "system_prompt_file",
    "scoped_skills",
    "input_schema",
    "output_schema",
)


class AgentRegistryError(Exception):
    """Raised when the agent registry cannot be built."""


@dataclass(frozen=True)
class ExpertAgentSpec:
    """Validated, normalised view of one expert agent YAML."""

    name: str
    display_name: str
    description: str
    system_prompt: str
    scoped_skills: tuple[str, ...]
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any]
    model: Optional[Mapping[str, Any]] = None
    max_iterations: int = 10
    emit_plan_steps: bool = True
    source_path: Optional[Path] = None
    # Availability (PR3): populated when the registry is loaded with a
    # ``skills_root``; both default to empty tuples in unit tests that skip
    # binary resolution.
    required_binaries: tuple[str, ...] = ()
    missing_binaries: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        """True when every declared external binary is on PATH.

        Agents whose scoped skills declare no external binary are always
        considered available (e.g. the ``report`` agent only renders HTML).
        """
        return not self.missing_binaries

    def to_tool_surface(self) -> dict[str, Any]:
        """Return the dict the Orchestrator hands to the LLM as a tool definition."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description.strip(),
                "parameters": dict(self.input_schema),
            },
        }



@dataclass
class AgentRegistry:
    """In-memory registry keyed by agent name."""

    agents: dict[str, ExpertAgentSpec] = field(default_factory=dict)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self.agents

    def __iter__(self) -> Iterable[ExpertAgentSpec]:
        return iter(self.agents.values())

    def __len__(self) -> int:
        return len(self.agents)

    def get(self, name: str) -> ExpertAgentSpec:
        try:
            return self.agents[name]
        except KeyError as exc:
            raise AgentRegistryError(f"unknown expert agent: {name}") from exc

    def names(self) -> list[str]:
        return sorted(self.agents)

    def tool_surfaces(self) -> list[dict[str, Any]]:
        """Tool surface list for the Orchestrator (sorted for stable prompts)."""
        return [self.agents[name].to_tool_surface() for name in self.names()]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_agent_registry(
    agents_dir: Path | str,
    *,
    skill_names: Iterable[str] | None = None,
    skills_root: Path | str | None = None,
    skill_binary_overrides: Mapping[str, str] | None = None,
) -> AgentRegistry:
    """Load and validate every ``*.yaml`` file under *agents_dir*.

    Parameters
    ----------
    agents_dir:
        Directory containing one YAML per expert agent.
    skill_names:
        Set of registered skill names. When provided, every entry of
        ``scoped_skills`` MUST appear in this set or loading aborts.
        When ``None``, scoped-skill resolution is skipped (useful for unit
        tests that don't load the full skill registry).
    skills_root:
        Root directory of installed skills. When provided, the registry
        computes ``required_binaries`` / ``missing_binaries`` per agent
        (PR3 availability contract). When ``None``, those fields stay
        empty and :attr:`ExpertAgentSpec.available` is ``True`` by default.
    skill_binary_overrides:
        Mapping of ``binary name -> absolute path`` (typically
        ``Config.tools.skill_binaries``). When a binary appears here AND
        the path exists on disk, it is considered resolved even if it is
        not on ``PATH``. This keeps the registry's availability view in
        sync with skill handlers that already honour
        ``tools.skill_binaries`` (see ``secbot/skills/*/handler.py``).
    """
    base = Path(agents_dir)
    if not base.is_dir():
        raise AgentRegistryError(f"agents_dir not found: {base}")

    known_skills = set(skill_names) if skill_names is not None else None
    overrides = dict(skill_binary_overrides or {})

    # Build ``skill_name -> external_binary`` once so we don't re-parse every
    # SKILL.md per agent. Only consulted when skills_root is provided.
    skill_binaries: dict[str, Optional[str]] = {}
    if skills_root is not None:
        from secbot.skills.metadata import scan_skills

        for name, meta in scan_skills(Path(skills_root)).items():
            skill_binaries[name] = meta.external_binary

    def _is_resolved(binary: str) -> bool:
        """Mirror the resolution order used by skill handlers.

        Priority: ``tools.skill_binaries[binary]`` (when the file exists)
        > ``shutil.which(binary)``. Anything else counts as missing.
        """
        override = overrides.get(binary)
        if override and Path(override).is_file():
            return True
        return shutil.which(binary) is not None

    registry = AgentRegistry()
    seen_skills: dict[str, str] = {}  # skill -> first agent claiming it

    for yaml_path in sorted(base.glob("*.yaml")):
        spec = _load_one(yaml_path, known_skills=known_skills)

        # Spec §5: a skill must not be shared across two expert agents.
        for skill in spec.scoped_skills:
            other = seen_skills.get(skill)
            if other is not None:
                raise AgentRegistryError(
                    f"skill '{skill}' is claimed by both '{other}' and '{spec.name}' "
                    "(see agent-registry-contract.md §5)"
                )
            seen_skills[skill] = spec.name

        if spec.name in registry.agents:
            raise AgentRegistryError(
                f"duplicate agent name '{spec.name}' from {yaml_path}"
            )

        if skills_root is not None:
            required = sorted({
                b for skill in spec.scoped_skills
                if (b := skill_binaries.get(skill))
            })
            missing = [b for b in required if not _is_resolved(b)]
            spec = ExpertAgentSpec(
                name=spec.name,
                display_name=spec.display_name,
                description=spec.description,
                system_prompt=spec.system_prompt,
                scoped_skills=spec.scoped_skills,
                input_schema=spec.input_schema,
                output_schema=spec.output_schema,
                model=spec.model,
                max_iterations=spec.max_iterations,
                emit_plan_steps=spec.emit_plan_steps,
                source_path=spec.source_path,
                required_binaries=tuple(required),
                missing_binaries=tuple(missing),
            )

        registry.agents[spec.name] = spec

    return registry


def _load_one(yaml_path: Path, *, known_skills: Optional[set[str]]) -> ExpertAgentSpec:
    try:
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise AgentRegistryError(f"{yaml_path}: invalid YAML: {exc}") from exc

    if not isinstance(raw, Mapping):
        raise AgentRegistryError(f"{yaml_path}: top level must be a mapping")

    missing = [f for f in REQUIRED_FIELDS if f not in raw]
    if missing:
        raise AgentRegistryError(
            f"{yaml_path}: missing required field(s): {', '.join(missing)}"
        )

    name = raw["name"]
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise AgentRegistryError(
            f"{yaml_path}: 'name' must match {NAME_RE.pattern}, got {name!r}"
        )
    if name != yaml_path.stem:
        raise AgentRegistryError(
            f"{yaml_path}: 'name' ({name}) must equal filename stem ({yaml_path.stem})"
        )

    scoped = raw["scoped_skills"]
    if not isinstance(scoped, list) or not scoped:
        raise AgentRegistryError(f"{yaml_path}: 'scoped_skills' must be a non-empty list")
    for item in scoped:
        if not isinstance(item, str):
            raise AgentRegistryError(
                f"{yaml_path}: scoped_skills entries must be strings, got {item!r}"
            )
    if known_skills is not None:
        unknown = [s for s in scoped if s not in known_skills]
        if unknown:
            raise AgentRegistryError(
                f"{yaml_path}: unknown skill(s) in scoped_skills: {', '.join(unknown)}"
            )

    prompt_rel = raw["system_prompt_file"]
    if not isinstance(prompt_rel, str) or not prompt_rel:
        raise AgentRegistryError(f"{yaml_path}: 'system_prompt_file' must be a string")
    prompt_path = (yaml_path.parent / prompt_rel).resolve()
    if not prompt_path.is_file():
        raise AgentRegistryError(
            f"{yaml_path}: system_prompt_file not found: {prompt_path}"
        )
    system_prompt = prompt_path.read_text(encoding="utf-8")

    in_schema = raw["input_schema"]
    out_schema = raw["output_schema"]
    _validate_schema(yaml_path, "input_schema", in_schema)
    _validate_schema(yaml_path, "output_schema", out_schema)

    model = raw.get("model")
    if model is not None and not isinstance(model, Mapping):
        raise AgentRegistryError(f"{yaml_path}: 'model' must be a mapping if present")

    max_iter = raw.get("max_iterations", 10)
    if not isinstance(max_iter, int) or max_iter <= 0:
        raise AgentRegistryError(
            f"{yaml_path}: 'max_iterations' must be a positive int, got {max_iter!r}"
        )

    emit = raw.get("emit_plan_steps", True)
    if not isinstance(emit, bool):
        raise AgentRegistryError(f"{yaml_path}: 'emit_plan_steps' must be a bool")

    display_name = raw["display_name"]
    if not isinstance(display_name, str) or not display_name.strip():
        raise AgentRegistryError(f"{yaml_path}: 'display_name' must be a non-empty string")

    description = raw["description"]
    if not isinstance(description, str) or not description.strip():
        raise AgentRegistryError(f"{yaml_path}: 'description' must be a non-empty string")

    return ExpertAgentSpec(
        name=name,
        display_name=display_name,
        description=description,
        system_prompt=system_prompt,
        scoped_skills=tuple(scoped),
        input_schema=in_schema,
        output_schema=out_schema,
        model=dict(model) if model else None,
        max_iterations=max_iter,
        emit_plan_steps=emit,
        source_path=yaml_path,
    )


def _validate_schema(yaml_path: Path, field_name: str, schema: Any) -> None:
    if not isinstance(schema, Mapping):
        raise AgentRegistryError(f"{yaml_path}: '{field_name}' must be a mapping")
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise AgentRegistryError(
            f"{yaml_path}: '{field_name}' is not a valid JSON Schema 2020-12: {exc.message}"
        ) from exc

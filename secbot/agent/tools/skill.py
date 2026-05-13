"""SkillTool: wrap a ``secbot/skills/<name>/`` package as a first-class LLM tool.

A Skill is a pre-written handler that validates arguments, runs a sandboxed
external binary (nmap / fscan / hydra / httpx / nuclei / ffuf / sqlmap / ...),
and returns a structured :class:`SkillResult`. Exposing each skill as a
dedicated ``Tool`` lets the LLM invoke it by name with typed parameters
(instead of synthesising a shell command via ``exec``).

The tool:

- ``name``       = ``SkillMetadata.name`` (e.g. ``nmap-port-scan``)
- ``description``= first paragraph of ``SKILL.md`` body (fallback: display_name)
- ``parameters`` = contents of ``input.schema.json``
- ``execute()``  = constructs a :class:`SkillContext`, routes through
  :class:`HighRiskGate` (critical skills require ``ctx.confirm``), invokes
  ``handler.run(args, ctx)``, and serialises the :class:`SkillResult` as a
  JSON string for the LLM.

Spec: ``.trellis/spec/backend/skill-contract.md`` +
``.trellis/spec/backend/high-risk-confirmation.md``.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import re
import shutil
import sys
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Optional

from secbot.agent.tools.base import Tool
from secbot.agents.high_risk import HighRiskGate
from secbot.skills.metadata import SkillMetadata, load_skill_metadata, scan_skills
from secbot.skills.types import (
    InvalidSkillArg,
    SkillBinaryMissing,
    SkillContext,
    SkillError,
    SkillResult,
)

_LOG = logging.getLogger(__name__)

# Front-matter block at the top of SKILL.md.
_FRONT_MATTER_RE = re.compile(r"^---\s*\r?\n.*?\r?\n---\s*\r?\n?", re.DOTALL)

# Cache modules loaded by file path so repeated instantiation is cheap.
_HANDLER_MODULE_CACHE: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# SkillContext binding — ContextVars let the loop inject scan_id / scan_dir /
# confirm / progress without threading them through every tool call.
# ---------------------------------------------------------------------------

_scan_id_var: ContextVar[str] = ContextVar("skill_scan_id", default="adhoc")
_scan_dir_var: ContextVar[Optional[Path]] = ContextVar("skill_scan_dir", default=None)
_confirm_var: ContextVar[Optional[Callable[[Mapping[str, Any]], Awaitable[bool]]]] = ContextVar(
    "skill_confirm", default=None
)
_progress_var: ContextVar[Optional[Callable[[float, str], Awaitable[None]]]] = ContextVar(
    "skill_progress", default=None
)


def bind_skill_context(
    *,
    scan_id: str,
    scan_dir: Path,
    confirm: Callable[[Mapping[str, Any]], Awaitable[bool]] | None = None,
    progress: Callable[[float, str], Awaitable[None]] | None = None,
) -> None:
    """Bind per-turn skill context so every SkillTool.execute sees fresh values."""
    _scan_id_var.set(scan_id)
    _scan_dir_var.set(scan_dir)
    _confirm_var.set(confirm)
    _progress_var.set(progress)


def current_skill_confirm() -> Callable[[Mapping[str, Any]], Awaitable[bool]] | None:
    """Return the active high-risk confirm callback, if any.

    Subagents rebind ``scan_id``/``scan_dir`` per task but must preserve the
    parent loop's confirm callback so critical skills inside the subagent
    still block on the WebUI dialog. Callers read the current value via this
    helper and pass it back into :func:`bind_skill_context`.
    """
    return _confirm_var.get()


def _current_scan_dir(default_workspace: Path) -> Path:
    scan_dir = _scan_dir_var.get()
    if scan_dir is not None:
        return scan_dir
    # Fallback: use an ephemeral per-session directory under the workspace so
    # raw logs never land outside the sandbox root. Created lazily.
    fallback = default_workspace / ".secbot" / "scans" / _scan_id_var.get()
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


# ---------------------------------------------------------------------------
# SkillTool
# ---------------------------------------------------------------------------


class SkillTool(Tool):
    """LLM-facing adapter for a single skill."""

    def __init__(
        self,
        *,
        meta: SkillMetadata,
        input_schema: Mapping[str, Any],
        handler_run: Callable[[dict[str, Any], SkillContext], Awaitable[SkillResult]],
        workspace: Path,
        description: str,
        high_risk_gate: HighRiskGate | None = None,
    ) -> None:
        self._meta = meta
        # Deep-copy is unnecessary here — ToolRegistry.get_definitions() only
        # reads the schema for serialisation.
        self._parameters = dict(input_schema)
        self._handler_run = handler_run
        self._workspace = workspace
        self._description = description
        self._high_risk_gate = high_risk_gate or HighRiskGate()

    @property
    def name(self) -> str:
        return self._meta.name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        # Tool.validate_params requires an object-typed schema; skills already
        # comply (all input.schema.json roots are type=object).
        return self._parameters

    @property
    def read_only(self) -> bool:
        # Network scans / brute force are never read-only; keep conservative.
        return False

    @property
    def exclusive(self) -> bool:
        # Critical skills prompt the user; running them in parallel would race
        # the confirmation dialog. Non-critical skills still share the sandbox
        # subprocess slot, so keep them exclusive for simplicity.
        return self._meta.is_critical()

    async def execute(self, **kwargs: Any) -> str:
        """Run the skill. Returns a JSON string (LLM-friendly)."""
        scan_id = _scan_id_var.get()
        scan_dir = _current_scan_dir(self._workspace)
        confirm = _confirm_var.get()
        progress = _progress_var.get()

        ctx_kwargs: dict[str, Any] = {"scan_id": scan_id, "scan_dir": scan_dir}
        if confirm is not None:
            ctx_kwargs["confirm"] = confirm
        if progress is not None:
            ctx_kwargs["progress"] = progress
        ctx = SkillContext(**ctx_kwargs)

        try:
            result = await self._high_risk_gate.guard(
                self._meta, kwargs, ctx, self._handler_run
            )
        except InvalidSkillArg as exc:
            return _error_payload(self._meta.name, "invalid_argument", str(exc))
        except SkillBinaryMissing as exc:
            return _error_payload(
                self._meta.name,
                "binary_missing",
                f"Required binary '{self._meta.external_binary or 'unknown'}' is not installed. "
                f"Install it or select a different skill. ({exc})",
            )
        except SkillError as exc:
            return _error_payload(self._meta.name, "skill_error", str(exc))
        except Exception as exc:  # pragma: no cover - surfaces as tool error
            _LOG.exception("SkillTool %s crashed", self._meta.name)
            return _error_payload(self._meta.name, "internal_error", str(exc))

        return _result_payload(self._meta, result)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def discover_skill_tools(
    skills_root: Path,
    workspace: Path,
    *,
    high_risk_gate: HighRiskGate | None = None,
    strict: bool = False,
    allow: set[str] | None = None,
) -> list[SkillTool]:
    """Scan ``skills_root`` and return a :class:`SkillTool` for each valid skill.

    Only directories whose ``SKILL.md`` passes :func:`load_skill_metadata`
    and which ship both ``handler.py`` and ``input.schema.json`` are picked
    up. Missing binaries are *not* filtered here — the loop decides whether
    to register offline skills (see Agent health flow in PR3).

    Args:
        skills_root: directory containing ``<name>/SKILL.md`` subdirectories.
        workspace: current run workspace, used for fallback scan_dir.
        high_risk_gate: optional shared gate (defaults to per-tool fresh gate).
        strict: when True, propagate SKILL.md validation errors.
        allow: when set, only return tools whose skill name is in this set.
    """
    tools: list[SkillTool] = []
    metas = scan_skills(skills_root, strict=strict)
    gate = high_risk_gate or HighRiskGate()
    for name, meta in metas.items():
        if allow is not None and name not in allow:
            continue
        try:
            tool = _build_skill_tool(meta, workspace=workspace, high_risk_gate=gate)
        except Exception as exc:  # noqa: BLE001
            if strict:
                raise
            _LOG.warning("Skipping skill %s: %s", name, exc)
            continue
        tools.append(tool)
    return tools


def build_skill_tool(
    skill_dir: Path,
    *,
    workspace: Path,
    high_risk_gate: HighRiskGate | None = None,
) -> SkillTool:
    """Build a :class:`SkillTool` for a single ``skill_dir`` (public helper).

    Used by tests and by future front-end custom-skill loading (PR4+).
    """
    meta = load_skill_metadata(skill_dir)
    return _build_skill_tool(meta, workspace=workspace, high_risk_gate=high_risk_gate or HighRiskGate())


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _build_skill_tool(
    meta: SkillMetadata,
    *,
    workspace: Path,
    high_risk_gate: HighRiskGate,
) -> SkillTool:
    skill_dir = meta.skill_dir
    input_schema = _load_input_schema(skill_dir)
    handler_run = _load_handler_run(skill_dir)
    description = _extract_description(skill_dir, meta)
    return SkillTool(
        meta=meta,
        input_schema=input_schema,
        handler_run=handler_run,
        workspace=workspace,
        description=description,
        high_risk_gate=high_risk_gate,
    )


def _load_input_schema(skill_dir: Path) -> dict[str, Any]:
    path = skill_dir / "input.schema.json"
    if not path.is_file():
        raise FileNotFoundError(f"{skill_dir}: missing input.schema.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(data, dict) or data.get("type") != "object":
        raise ValueError(f"{path}: root schema must have type=object")
    return data


def _load_handler_run(
    skill_dir: Path,
) -> Callable[[dict[str, Any], SkillContext], Awaitable[SkillResult]]:
    handler_path = skill_dir / "handler.py"
    if not handler_path.is_file():
        raise FileNotFoundError(f"{skill_dir}: missing handler.py")

    cache_key = str(handler_path.resolve())
    module = _HANDLER_MODULE_CACHE.get(cache_key)
    if module is None:
        # Use a dotted module name so relative imports inside the handler
        # (should any appear) behave predictably; dashes are replaced with
        # underscores so Python's import system accepts it.
        module_name = f"secbot._skill_handlers.{skill_dir.name.replace('-', '_')}"
        spec = importlib.util.spec_from_file_location(module_name, handler_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load handler module at {handler_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        _HANDLER_MODULE_CACHE[cache_key] = module

    run = getattr(module, "run", None)
    if not callable(run):
        raise AttributeError(f"{handler_path}: missing async `run(args, ctx)` function")
    return run  # type: ignore[return-value]


def _extract_description(skill_dir: Path, meta: SkillMetadata) -> str:
    """Use the first non-empty paragraph of SKILL.md body as tool description.

    LLM tool selection depends heavily on the description; we prefer the
    human-authored body text over the terse display name.
    """
    md_path = skill_dir / "SKILL.md"
    try:
        raw = md_path.read_text(encoding="utf-8")
    except OSError:
        return meta.display_name
    body = _FRONT_MATTER_RE.sub("", raw, count=1).strip()
    if not body:
        return meta.display_name
    # First paragraph (split on blank line).
    first_para = body.split("\n\n", 1)[0].strip()
    # Collapse internal whitespace for a clean single-line schema.
    cleaned = " ".join(first_para.split())
    if len(cleaned) > 400:
        cleaned = cleaned[:397] + "..."
    return cleaned or meta.display_name


def _result_payload(meta: SkillMetadata, result: SkillResult) -> str:
    """Serialise :class:`SkillResult` for the LLM.

    Keeping summary small is critical — handlers guarantee bounded sizes but
    we still cap ``findings`` defensively so one run can't blow the context
    window.
    """
    findings = list(result.findings)[:50]
    cmdb_writes = list(result.cmdb_writes)[:50]
    payload = {
        "skill": meta.name,
        "summary": result.summary,
        "raw_log_path": result.raw_log_path,
        "findings": findings,
        "cmdb_writes": cmdb_writes,
    }
    return json.dumps(payload, ensure_ascii=False, default=str)


def _error_payload(skill_name: str, error_type: str, message: str) -> str:
    return json.dumps(
        {
            "skill": skill_name,
            "error": {"type": error_type, "message": message},
        },
        ensure_ascii=False,
    )


def skill_required_binaries(skills_root: Path, skill_names: list[str]) -> list[str]:
    """Return the set of external binaries declared by the given skills.

    Used by ``AgentRegistry.check_availability`` (PR3) to decide whether a
    specialist agent is online.
    """
    metas = scan_skills(skills_root)
    bins: set[str] = set()
    for name in skill_names:
        meta = metas.get(name)
        if meta and meta.external_binary:
            bins.add(meta.external_binary)
    return sorted(bins)


def missing_binaries(required: list[str]) -> list[str]:
    """Subset of ``required`` binaries that are NOT available on PATH."""
    return [b for b in required if not shutil.which(b)]

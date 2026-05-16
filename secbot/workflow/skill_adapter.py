"""Skill registry adapter for the workflow engine.

Exposes ``secbot/skills/<name>/handler.py`` so ``kind=tool`` workflow
steps can invoke the pentest skills (fscan / nmap / nuclei / report /
…) from the UI. The adapter implements the subset of the
``ToolRegistry`` protocol the workflow layer consumes:

* ``tool_names``  — iterable of registered skill names.
* ``has(name)``   — membership check.
* ``get(name)``   — a lightweight object exposing ``.name`` /
  ``.display_name`` / ``.description`` / ``.parameters`` (JSON
  Schema for ``args``) / ``.output_schema``.
* ``await execute(name, args)``  — runs ``handler.run`` with a
  freshly built :class:`SkillContext` and returns a JSON-ready dict.

This is what the UI dropdown and the ``ToolExecutor`` actually talk
to when the user picks ``kind=tool`` + a skill name from the
``/api/workflows/_tools`` list.
"""

from __future__ import annotations

import importlib.util
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from secbot.skills.metadata import SkillMetadata, scan_skills
from secbot.skills.types import SkillContext, SkillResult


_DEFAULT_SKILLS_ROOT = Path(__file__).resolve().parents[1] / "skills"


@dataclass(frozen=True)
class _SkillTool:
    """Lightweight tool descriptor surfaced to the workflow layer."""

    name: str
    display_name: str
    description: str
    parameters: dict[str, Any]
    output_schema: dict[str, Any]

    # The workflow layer reads ``tool.parameters`` for the input schema
    # and ``tool.output_schema`` for the output schema; both are plain
    # JSON-Schema dicts loaded from ``<skill>/input.schema.json`` and
    # ``<skill>/output.schema.json`` respectively.


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _read_description(skill_dir: Path) -> str:
    """Return the body of ``SKILL.md`` after the front-matter."""
    md_path = skill_dir / "SKILL.md"
    try:
        text = md_path.read_text(encoding="utf-8")
    except OSError:
        return ""
    if not text.startswith("---\n"):
        return text.strip()
    try:
        _, _raw, body = text.split("---\n", 2)
    except ValueError:
        return ""
    return body.strip()


def _load_handler(skill_dir: Path):
    """Import ``handler.py`` from *skill_dir* and return its ``run`` coroutine.

    Skills live outside the ``secbot.skills`` package path for some of
    the directories that don't follow the full schema, so we load by
    explicit file spec. Cached handlers are fine because reloading a
    skill at runtime is not a supported operation.
    """
    handler_path = skill_dir / "handler.py"
    if not handler_path.is_file():
        return None
    module_name = f"secbot.skills.{skill_dir.name}.handler"
    spec = importlib.util.spec_from_file_location(module_name, handler_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, "run", None)


def _serialize_result(result: Any) -> Any:
    """Turn a :class:`SkillResult` (or arbitrary handler return) into JSON."""
    if isinstance(result, SkillResult):
        return {
            "summary": result.summary,
            "findings": list(result.findings),
            "cmdb_writes": list(result.cmdb_writes),
            "raw_log_path": result.raw_log_path,
        }
    return result


class SkillToolRegistryAdapter:
    """Expose the on-disk skill catalogue as a ``ToolRegistry``.

    Only skills that pass :func:`secbot.skills.metadata.scan_skills`
    AND ship a ``handler.py`` are listed — that way the UI dropdown
    only shows entries that can actually run as a workflow step.
    """

    def __init__(
        self,
        *,
        skills_root: Path | None = None,
        scan_root: Path | None = None,
        fallback_registry: Any = None,
    ) -> None:
        self._skills_root = Path(skills_root) if skills_root else _DEFAULT_SKILLS_ROOT
        self._scan_root = Path(scan_root) if scan_root else (self._skills_root.parent.parent / "workspace" / "workflow_scans")
        # Optional secondary registry (typically the agent's
        # ``ToolRegistry`` containing ``exec`` / ``read_file`` / etc.).
        # ``has`` / ``execute`` fall through to it when a name is not a
        # known skill — this keeps ``kind=script`` steps working (the
        # ``ScriptExecutor`` shells out via the ``exec`` tool) without
        # polluting the workflow-builder dropdown, which still only
        # iterates over real skills via :pyattr:`tool_names`.
        self._fallback = fallback_registry
        self._metadata: dict[str, SkillMetadata] = {}
        self._tools: dict[str, _SkillTool] = {}
        self._reload()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _reload(self) -> None:
        metadata = scan_skills(self._skills_root, strict=False)
        tools: dict[str, _SkillTool] = {}
        for name, meta in metadata.items():
            if not (meta.skill_dir / "handler.py").is_file():
                # Skills without a Python handler (e.g. markdown-only
                # ``skill-creator``) cannot be executed from the
                # workflow layer, so exclude them from the catalogue.
                continue
            input_schema = _load_json(meta.skill_dir / "input.schema.json")
            output_schema = _load_json(meta.skill_dir / "output.schema.json")
            description = _read_description(meta.skill_dir) or meta.display_name
            tools[name] = _SkillTool(
                name=name,
                display_name=meta.display_name,
                description=description,
                parameters=input_schema,
                output_schema=output_schema,
            )
        self._metadata = metadata
        self._tools = tools

    # ------------------------------------------------------------------
    # ToolRegistry protocol — consumed by workflow_routes.handle_tools
    # and secbot.workflow.executors.tool.ToolExecutor.
    # ------------------------------------------------------------------

    @property
    def tool_names(self) -> list[str]:
        return sorted(self._tools)

    def has(self, name: str) -> bool:
        if name in self._tools:
            return True
        if self._fallback is not None:
            try:
                return bool(self._fallback.has(name))
            except Exception:
                return False
        return False

    def get(self, name: str) -> _SkillTool | None:
        return self._tools.get(name)

    def __iter__(self) -> Iterable[_SkillTool]:  # pragma: no cover - convenience
        return iter(self._tools.values())

    async def execute(self, name: str, args: dict[str, Any]) -> Any:
        """Invoke the skill handler and return a JSON-serialisable payload.

        The caller (``ToolExecutor``) treats a string starting with
        ``"Error"`` as a failure (matching the native registry), so we
        mirror that convention for missing skills / import errors.
        """
        meta = self._metadata.get(name)
        if meta is None:
            # Fall through to the agent tool registry so ``kind=script``
            # (which invokes the ``exec`` tool) and any other built-in
            # tool can run from a workflow step.
            if self._fallback is not None:
                try:
                    has = self._fallback.has(name)
                except Exception:
                    has = False
                if has:
                    return await self._fallback.execute(name, args or {})
            return f"Error: skill '{name}' is not registered"
        handler = _load_handler(meta.skill_dir)
        if handler is None:
            return f"Error: skill '{name}' has no handler.run"

        scan_id = f"wf-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"
        scan_dir = self._scan_root / scan_id
        scan_dir.mkdir(parents=True, exist_ok=True)
        ctx = SkillContext(scan_id=scan_id, scan_dir=scan_dir)

        try:
            result = await handler(args or {}, ctx)
        except Exception as exc:  # noqa: BLE001 - surfaced to UI
            return f"Error: skill '{name}' failed: {exc}"
        return _serialize_result(result)

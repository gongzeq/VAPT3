"""Shared fixtures for skill handler tests."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

import pytest

from secbot.skills._shared.sandbox import SandboxResult
from secbot.skills.types import SkillContext

_SKILLS_ROOT = Path(__file__).resolve().parents[2] / "secbot" / "skills"


def load_handler(skill_name: str) -> ModuleType:
    """Load ``<skill_name>/handler.py`` as a module (skill dirs use hyphens)."""
    mod_name = f"_secbot_skill_{skill_name.replace('-', '_')}_handler"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    path = _SKILLS_ROOT / skill_name / "handler.py"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def handler_loader():
    return load_handler


@pytest.fixture()
def make_ctx(tmp_path: Path) -> Callable[..., SkillContext]:
    def _build(**overrides: Any) -> SkillContext:
        scan_dir = tmp_path / overrides.get("scan_id", "scan-test")
        scan_dir.mkdir(parents=True, exist_ok=True)
        return SkillContext(
            scan_id=overrides.get("scan_id", "scan-test"),
            scan_dir=scan_dir,
            cancel_token=overrides.get("cancel_token", asyncio.Event()),
        )

    return _build


@pytest.fixture()
def fake_run_command(monkeypatch):
    """Patch ``run_command`` in the given handler modules.

    The fake writes ``stdout`` into ``raw_log_path`` (if any) and returns a
    ``SandboxResult`` with the requested ``exit_code``.
    """

    def _install(
        *targets,
        stdout: bytes = b"",
        exit_code: int = 0,
        exc: Exception | None = None,
    ):
        async def _fake(**kwargs):
            if exc is not None:
                raise exc
            raw = kwargs.get("raw_log_path")
            if raw is not None:
                Path(raw).parent.mkdir(parents=True, exist_ok=True)
                Path(raw).write_bytes(stdout)
            return SandboxResult(
                exit_code=exit_code,
                raw_log_path=raw,
                captured=None,
            )

        for t in targets:
            if isinstance(t, ModuleType):
                monkeypatch.setattr(t, "run_command", _fake, raising=True)
            else:
                monkeypatch.setattr(f"{t}.run_command", _fake, raising=True)

    return _install

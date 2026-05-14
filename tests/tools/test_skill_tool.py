"""Unit tests for SkillTool discovery + execution plumbing.

Covers the PR1 contract of
``secbot/agent/tools/skill.py``:

- ``discover_skill_tools`` returns one SkillTool per valid skill directory
- ``SkillTool.to_schema`` exposes the JSON Schema from ``input.schema.json``
- ``SkillTool.execute`` runs the handler and returns a JSON string
- Invalid arguments surface as a structured error payload (no crash)
- ``critical`` skills route through ``HighRiskGate.guard`` (user denial path)
"""

from __future__ import annotations

import asyncio
import json
import textwrap
from pathlib import Path

import pytest

from secbot.agent.tools.skill import (
    SkillTool,
    bind_skill_context,
    discover_skill_tools,
)
from secbot.agents.high_risk import HighRiskGate
from secbot.skills.types import SkillContext, SkillResult


def _write_skill(
    root: Path,
    name: str,
    *,
    risk: str = "low",
    body: str = "Probe thing X.",
    handler_body: str,
    input_schema: dict | None = None,
) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        textwrap.dedent(
            f"""\
            ---
            name: {name}
            display_name: Test {name}
            version: 1.0.0
            risk_level: {risk}
            category: test
            external_binary: none
            network_egress: none
            expected_runtime_sec: 5
            summary_size_hint: small
            ---

            {body}
            """
        ),
        encoding="utf-8",
    )
    schema = input_schema or {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["target"],
        "additionalProperties": False,
        "properties": {
            "target": {"type": "string", "minLength": 1},
            "ports": {"type": "string"},
        },
    }
    (skill_dir / "input.schema.json").write_text(
        json.dumps(schema), encoding="utf-8"
    )
    (skill_dir / "output.schema.json").write_text(
        json.dumps({"type": "object", "additionalProperties": True}),
        encoding="utf-8",
    )
    (skill_dir / "handler.py").write_text(handler_body, encoding="utf-8")
    return skill_dir


@pytest.fixture
def skills_root(tmp_path: Path) -> Path:
    root = tmp_path / "skills"
    root.mkdir()
    _write_skill(
        root,
        "echo-skill",
        risk="low",
        body="Echo back target. First paragraph becomes tool description.",
        handler_body=textwrap.dedent(
            """\
            from secbot.skills.types import SkillContext, SkillResult

            async def run(args, ctx: SkillContext) -> SkillResult:
                return SkillResult(summary={"target": args["target"], "scan_id": ctx.scan_id})
            """
        ),
    )
    _write_skill(
        root,
        "danger-skill",
        risk="critical",
        body="Dangerous op — requires confirmation.",
        handler_body=textwrap.dedent(
            """\
            from secbot.skills.types import SkillContext, SkillResult

            async def run(args, ctx: SkillContext) -> SkillResult:
                return SkillResult(summary={"ran": True})
            """
        ),
    )
    return root


def test_discover_returns_tool_per_valid_skill(tmp_path: Path, skills_root: Path) -> None:
    tools = discover_skill_tools(skills_root, workspace=tmp_path)
    names = sorted(t.name for t in tools)
    assert names == ["danger-skill", "echo-skill"]


def test_schema_is_exposed_from_input_schema(tmp_path: Path, skills_root: Path) -> None:
    tools = {t.name: t for t in discover_skill_tools(skills_root, workspace=tmp_path)}
    schema = tools["echo-skill"].to_schema()
    assert schema["type"] == "function"
    fn = schema["function"]
    assert fn["name"] == "echo-skill"
    assert "Echo back target" in fn["description"]
    assert fn["parameters"]["required"] == ["target"]


def test_execute_runs_handler_and_returns_json(tmp_path: Path, skills_root: Path) -> None:
    tools = {t.name: t for t in discover_skill_tools(skills_root, workspace=tmp_path)}
    scan_dir = tmp_path / "scan"
    scan_dir.mkdir()
    bind_skill_context(scan_id="unit-1", scan_dir=scan_dir)

    raw = asyncio.run(tools["echo-skill"].execute(target="example.com"))
    payload = json.loads(raw)
    assert payload["skill"] == "echo-skill"
    assert payload["summary"] == {"target": "example.com", "scan_id": "unit-1"}
    assert payload["findings"] == []


def test_execute_invalid_handler_surface_error(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    root.mkdir()
    _write_skill(
        root,
        "broken-skill",
        handler_body=textwrap.dedent(
            """\
            from secbot.skills.types import InvalidSkillArg, SkillContext, SkillResult

            async def run(args, ctx: SkillContext) -> SkillResult:
                raise InvalidSkillArg("bad target shape")
            """
        ),
    )
    tools = {t.name: t for t in discover_skill_tools(root, workspace=tmp_path)}
    bind_skill_context(scan_id="unit-2", scan_dir=tmp_path)
    raw = asyncio.run(tools["broken-skill"].execute(target="x"))
    payload = json.loads(raw)
    assert payload["error"]["type"] == "invalid_argument"
    assert "bad target shape" in payload["error"]["message"]


def test_critical_skill_denied_by_default_confirm(tmp_path: Path, skills_root: Path) -> None:
    """Without a user-facing confirm callback, critical skills are denied (fail-safe)."""
    tools = {t.name: t for t in discover_skill_tools(
        skills_root, workspace=tmp_path, high_risk_gate=HighRiskGate()
    )}
    bind_skill_context(scan_id="unit-3", scan_dir=tmp_path)
    raw = asyncio.run(tools["danger-skill"].execute(target="10.0.0.1"))
    payload = json.loads(raw)
    # HighRiskGate returns a SkillResult with user_denied=True when the
    # default (no-op) confirm callback rejects; the tool serialises it in
    # the summary, not as an error.
    assert payload["summary"].get("user_denied") is True
    assert payload["summary"].get("reason") == "denied"


def test_critical_skill_exclusive(tmp_path: Path, skills_root: Path) -> None:
    tools = {t.name: t for t in discover_skill_tools(skills_root, workspace=tmp_path)}
    assert tools["danger-skill"].exclusive is True
    assert tools["echo-skill"].exclusive is False


def test_validate_params_rejects_missing_required(tmp_path: Path, skills_root: Path) -> None:
    tools = {t.name: t for t in discover_skill_tools(skills_root, workspace=tmp_path)}
    errors = tools["echo-skill"].validate_params({})
    assert any("target" in e for e in errors)


def test_execute_persists_cmdb_writes(tmp_path: Path) -> None:
    """SkillTool.execute applies cmdb_writes to the CMDB and auto-creates the scan."""
    import asyncio

    from secbot.cmdb import db as cmdb_db
    from secbot.cmdb.models import Base

    db_file = tmp_path / "cmdb.sqlite3"
    cmdb_db.init_engine(f"sqlite+aiosqlite:///{db_file}")

    async def _setup() -> None:
        async with cmdb_db.get_engine().begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_setup())

    root = tmp_path / "skills"
    root.mkdir()
    _write_skill(
        root,
        "persist-skill",
        handler_body=textwrap.dedent(
            """\
            from secbot.skills.types import SkillContext, SkillResult

            async def run(args, ctx: SkillContext) -> SkillResult:
                return SkillResult(
                    summary={"ok": True},
                    cmdb_writes=[
                        {
                            "table": "assets",
                            "op": "upsert",
                            "data": {"target": "10.0.0.1", "ip": "10.0.0.1"},
                        }
                    ],
                )
            """
        ),
    )
    tools = {t.name: t for t in discover_skill_tools(root, workspace=tmp_path)}
    bind_skill_context(scan_id="unit-cmdb", scan_dir=tmp_path)

    raw = asyncio.run(tools["persist-skill"].execute(target="10.0.0.1"))
    payload = json.loads(raw)
    assert payload["summary"] == {"ok": True}
    assert len(payload["cmdb_writes"]) == 1

    # Verify CMDB side effects
    async def _verify() -> None:
        from secbot.cmdb.repo import get_scan, list_assets

        async with cmdb_db.get_session() as session:
            scan = await get_scan(session, "local", "unit-cmdb")
            assert scan is not None
            assert scan.target == "10.0.0.1"
            assets = await list_assets(session, "local", scan_id="unit-cmdb")
            assert len(assets) == 1
            assert assets[0].target == "10.0.0.1"

    asyncio.run(_verify())
    asyncio.run(cmdb_db.dispose_engine())

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
    bind_skill_context,
    current_asset_auto_management_enabled,
    discover_skill_tools,
)
from secbot.agents.high_risk import HighRiskGate


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
    assert payload["raw_log_path"] is None
    assert payload["artifacts"] == {}
    assert payload["summary"] == {"target": "example.com", "scan_id": "unit-1"}
    assert payload["findings"] == []
    assert current_asset_auto_management_enabled() is False


def test_execute_surfaces_artifact_paths_before_large_summary(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    root.mkdir()
    _write_skill(
        root,
        "artifact-skill",
        handler_body=textwrap.dedent(
            """\
            from secbot.skills.types import SkillContext, SkillResult

            async def run(args, ctx: SkillContext) -> SkillResult:
                raw_urls = ctx.scan_dir / "katana" / "katana_urls.txt"
                raw_log = ctx.raw_log_dir / "katana-crawl-web.log"
                return SkillResult(
                    summary={
                        "raw_urls_path": str(raw_urls),
                        "scan_dir": str(ctx.scan_dir),
                        "candidates": [{"url": f"https://example.com/{i}", "blob": "x" * 200} for i in range(100)],
                    },
                    raw_log_path=str(raw_log),
                )
            """
        ),
    )
    tools = {t.name: t for t in discover_skill_tools(root, workspace=tmp_path)}
    scan_dir = tmp_path / "scan-artifacts"
    bind_skill_context(scan_id="unit-artifacts", scan_dir=scan_dir)

    raw = asyncio.run(tools["artifact-skill"].execute(target="example.com"))

    assert raw.index('"raw_log_path"') < raw.index('"summary"')
    assert raw.index('"artifacts"') < raw.index('"summary"')
    assert str(scan_dir / "katana" / "katana_urls.txt") in raw[:1200]
    payload = json.loads(raw)
    assert payload["artifacts"]["raw_urls_path"] == str(
        scan_dir / "katana" / "katana_urls.txt"
    )
    assert payload["artifacts"]["raw_log_path"] == str(
        scan_dir / "raw" / "katana-crawl-web.log"
    )


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
    bind_skill_context(scan_id="unit-cmdb-disabled", scan_dir=tmp_path)

    raw = asyncio.run(tools["persist-skill"].execute(target="10.0.0.1"))
    payload = json.loads(raw)
    assert payload["summary"] == {"ok": True}
    assert len(payload["cmdb_writes"]) == 1

    async def _verify_disabled() -> None:
        from secbot.cmdb.repo import get_scan, list_assets

        async with cmdb_db.get_session() as session:
            scan = await get_scan(session, "local", "unit-cmdb-disabled")
            assert scan is None
            assets = await list_assets(session, "local", scan_id="unit-cmdb-disabled")
            assert assets == []

    asyncio.run(_verify_disabled())

    bind_skill_context(
        scan_id="unit-cmdb",
        scan_dir=tmp_path,
        asset_auto_management_enabled=True,
    )

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


def test_execute_bridges_confirmed_findings_to_vulnerability_store_and_feed(tmp_path: Path) -> None:
    """Host bridge captures confirmed SkillResult.findings even when CMDB writes are gated off."""
    from secbot.agent.asset_feed import AssetFeed
    from secbot.agent.vulnerability_store import VulnerabilityStore

    root = tmp_path / "skills"
    root.mkdir()
    _write_skill(
        root,
        "finding-skill",
        handler_body=textwrap.dedent(
            """\
            from secbot.skills.types import SkillContext, SkillResult

            async def run(args, ctx: SkillContext) -> SkillResult:
                return SkillResult(
                    summary={"ok": True},
                    findings=[
                        {
                            "test_name": "SQL Error Probe",
                            "result": "positive",
                            "confidence": "high",
                            "url": "http://example.test/login?id=1",
                            "evidence": "database error marker reflected",
                        }
                    ],
                    cmdb_writes=[
                        {
                            "table": "vulnerabilities",
                            "op": "upsert",
                            "data": {
                                "target": "example.test",
                                "severity": "high",
                                "category": "injection",
                                "title": "SQL Error Probe detected",
                            },
                        }
                    ],
                )
            """
        ),
    )
    tools = {t.name: t for t in discover_skill_tools(root, workspace=tmp_path)}
    feed = AssetFeed()
    store = VulnerabilityStore()
    bind_skill_context(
        scan_id="unit-finding",
        scan_dir=tmp_path,
        asset_auto_management_enabled=False,
        asset_feed=feed,
        vulnerability_store=store,
    )

    raw = asyncio.run(tools["finding-skill"].execute(target="example.test"))
    payload = json.loads(raw)
    assert payload["summary"] == {"ok": True}
    assert len(store) == 1

    stored = asyncio.run(store.to_dict_list())
    assert stored[0]["title"] == "SQL Error Probe"
    assert stored[0]["severity"] == "high"
    assert stored[0]["category"] == "injection"
    assert stored[0]["verification_method"] == "automated_scan"

    entries = asyncio.run(feed.since())
    assert [entry.kind for entry in entries] == ["vuln"]
    assert entries[0].payload["category"] == "injection"


def test_execute_bridges_all_confirmed_findings_without_context_payload_cap(
    tmp_path: Path,
) -> None:
    """Host persistence must not inherit the model-facing 50-finding payload cap."""
    from secbot.agent.asset_feed import AssetFeed
    from secbot.agent.vulnerability_store import VulnerabilityStore

    root = tmp_path / "skills"
    root.mkdir()
    _write_skill(
        root,
        "many-findings-skill",
        handler_body=textwrap.dedent(
            """\
            from secbot.skills.types import SkillContext, SkillResult

            async def run(args, ctx: SkillContext) -> SkillResult:
                return SkillResult(
                    summary={"ok": True},
                    findings=[
                        {
                            "title": f"Confirmed finding {i}",
                            "result": "positive",
                            "confidence": "high",
                            "url": f"http://example.test/item/{i}",
                            "evidence": f"proof {i}",
                        }
                        for i in range(55)
                    ],
                )
            """
        ),
    )
    tools = {t.name: t for t in discover_skill_tools(root, workspace=tmp_path)}
    feed = AssetFeed()
    store = VulnerabilityStore()
    bind_skill_context(
        scan_id="unit-many-findings",
        scan_dir=tmp_path,
        asset_auto_management_enabled=False,
        asset_feed=feed,
        vulnerability_store=store,
    )

    raw = asyncio.run(tools["many-findings-skill"].execute(target="example.test"))
    payload = json.loads(raw)
    assert len(payload["findings"]) == 50
    assert len(store) == 55
    assert len(asyncio.run(feed.since())) == 55


def test_execute_bridges_unverified_findings_as_candidates_not_confirmed(tmp_path: Path) -> None:
    """Passive scanner hits must not enter the confirmed vulnerability store."""
    from secbot.agent.asset_feed import AssetFeed
    from secbot.agent.vulnerability_store import VulnerabilityStore

    root = tmp_path / "skills"
    root.mkdir()
    _write_skill(
        root,
        "candidate-skill",
        handler_body=textwrap.dedent(
            """\
            from secbot.skills.types import SkillContext, SkillResult

            async def run(args, ctx: SkillContext) -> SkillResult:
                return SkillResult(
                    summary={"ok": True},
                    findings=[
                        {
                            "template_id": "cve-passive-template",
                            "severity": "medium",
                            "host": "example.test",
                            "matched_at": "http://example.test/",
                            "name": "Passive scanner match",
                        }
                    ],
                )
            """
        ),
    )
    tools = {t.name: t for t in discover_skill_tools(root, workspace=tmp_path)}
    feed = AssetFeed()
    store = VulnerabilityStore()
    bind_skill_context(
        scan_id="unit-candidate",
        scan_dir=tmp_path,
        asset_auto_management_enabled=False,
        asset_feed=feed,
        vulnerability_store=store,
    )

    raw = asyncio.run(tools["candidate-skill"].execute(target="example.test"))
    payload = json.loads(raw)
    assert payload["summary"] == {"ok": True}
    assert len(store) == 0

    entries = asyncio.run(feed.since())
    assert [entry.kind for entry in entries] == ["vulnerability_candidate"]
    assert entries[0].payload["candidate"] is True
    assert entries[0].payload["status"] == "candidate"


def test_execute_persists_unverified_findings_as_cmdb_candidates_when_enabled(
    tmp_path: Path,
) -> None:
    """Asset Auto-Management persists unverified Skill findings as CMDB candidates."""
    from secbot.agent.asset_feed import AssetFeed
    from secbot.agent.vulnerability_store import VulnerabilityStore
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
        "candidate-cmdb-skill",
        handler_body=textwrap.dedent(
            """\
            from secbot.skills.types import SkillContext, SkillResult

            async def run(args, ctx: SkillContext) -> SkillResult:
                return SkillResult(
                    summary={"ok": True},
                    findings=[
                        {
                            "template_id": "passive-candidate-template",
                            "severity": "medium",
                            "host": "example.test",
                            "matched_at": "http://example.test/",
                            "name": "Passive scanner match",
                        }
                    ],
                )
            """
        ),
    )
    tools = {t.name: t for t in discover_skill_tools(root, workspace=tmp_path)}
    feed = AssetFeed()
    store = VulnerabilityStore()
    bind_skill_context(
        scan_id="unit-candidate-cmdb",
        scan_dir=tmp_path,
        asset_auto_management_enabled=True,
        asset_feed=feed,
        vulnerability_store=store,
    )

    raw = asyncio.run(tools["candidate-cmdb-skill"].execute(target="example.test"))
    payload = json.loads(raw)
    assert payload["summary"] == {"ok": True}
    assert len(store) == 0

    entries = asyncio.run(feed.since())
    assert [entry.kind for entry in entries] == ["vulnerability_candidate"]

    async def _verify() -> None:
        from secbot.cmdb.repo import list_assets, list_vulnerability_candidates

        async with cmdb_db.get_session() as session:
            assets = await list_assets(session, "local", scan_id="unit-candidate-cmdb")
            candidates = await list_vulnerability_candidates(session, "local")
            assert len(assets) == 1
            assert assets[0].target == "example.test"
            assert len(candidates) == 1
            assert candidates[0].title == "Passive scanner match"
            assert candidates[0].status == "candidate"
            assert candidates[0].source == "candidate-cmdb-skill"

    asyncio.run(_verify())
    asyncio.run(cmdb_db.dispose_engine())

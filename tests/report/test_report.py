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
            evidence={"summary": "RCE on /api"},
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
    assert "# Security Scan Report" in md
    assert "Log4Shell" in md
    assert "CVE-2021-44228" in md
    assert "10.0.0.5" in md
    assert "| critical | 1 |" in md


async def test_render_html_inlines_severity_badges(cmdb_engine):
    scan_id = await _seed()
    async with cmdb_db.get_session() as session:
        model = await build_report_model(session, scan_id)
    html = render_html(model)
    assert "<!DOCTYPE html>" in html
    assert "sev-critical" in html
    assert "Log4Shell" in html


# ---------------------------------------------------------------------------
# Skill handlers
# ---------------------------------------------------------------------------


def _ctx(tmp_path: Path) -> SkillContext:
    sd = tmp_path / "scan-001"
    sd.mkdir(parents=True, exist_ok=True)
    return SkillContext(scan_id="scan-001", scan_dir=sd)


async def test_report_markdown_skill_writes_file(cmdb_engine, tmp_path: Path):
    scan_id = await _seed()
    mod = _load("report-markdown")
    res = await mod.run({"scan_id": scan_id}, _ctx(tmp_path))
    assert res.summary["status"] == "ok"
    out = Path(res.summary["report_path"])
    assert out.exists()
    assert "Log4Shell" in out.read_text(encoding="utf-8")


async def test_report_markdown_skill_empty_scan(cmdb_engine, tmp_path: Path):
    # Create an empty scan with no assets.
    async with cmdb_db.get_session() as session:
        scan = await create_scan(session, "local", target="10.10.10.10")
    mod = _load("report-markdown")
    res = await mod.run({"scan_id": scan.id}, _ctx(tmp_path))
    assert res.summary["status"] == "empty"
    assert res.summary["report_path"] is None


async def test_report_docx_skill_writes_file(cmdb_engine, tmp_path: Path):
    scan_id = await _seed()
    mod = _load("report-docx")
    res = await mod.run({"scan_id": scan_id}, _ctx(tmp_path))
    assert res.summary["status"] == "ok"
    out = Path(res.summary["report_path"])
    assert out.exists()
    assert out.stat().st_size > 1000  # non-trivial DOCX


async def test_report_pdf_skill_handles_missing_dep(
    cmdb_engine, tmp_path: Path, monkeypatch
):
    """If WeasyPrint is missing the skill MUST fail-fast with status=error."""
    import secbot.report.render as render_mod

    def _boom(*_a, **_k):
        from secbot.report.builder import ReportRenderError

        raise ReportRenderError("weasyprint not installed")

    monkeypatch.setattr(render_mod, "render_pdf", _boom)
    # Reload the handler so it picks up the patched render_pdf.
    sys.modules.pop("_secbot_skill_report_pdf_handler", None)
    mod = _load("report-pdf")

    scan_id = await _seed()
    res = await mod.run({"scan_id": scan_id}, _ctx(tmp_path))
    assert res.summary["status"] == "error"
    assert "weasyprint" in res.summary["error"]

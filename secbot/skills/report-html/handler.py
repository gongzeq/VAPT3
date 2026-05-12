"""report-html handler.

Renders the canonical HTML report into ``<scan_dir>/report/report.html``.
The HTML format is the single supported export (markdown / pdf / docx were
retired in favour of one canonical deliverable).
"""

from __future__ import annotations

from typing import Any

from secbot.cmdb.db import get_session
from secbot.cmdb.models import DEFAULT_ACTOR
from secbot.report.builder import build_report_model, record_report_meta
from secbot.report.render import render_html
from secbot.skills.types import SkillContext, SkillResult


async def run(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    scan_id: str = args["scan_id"]
    actor_id: str = args.get("actor_id", DEFAULT_ACTOR)
    report_title: str = args.get("title") or f"Scan {scan_id} report"
    report_type: str = args.get("type", "custom")

    async with get_session() as session:
        model = await build_report_model(session, scan_id, actor_id=actor_id)

    if model.is_empty():
        return SkillResult(
            summary={
                "status": "empty",
                "report_path": None,
                "asset_count": 0,
                "finding_count": 0,
            }
        )

    html = render_html(model)
    report_dir = ctx.scan_dir / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    out_path = report_dir / "report.html"
    out_path.write_text(html, encoding="utf-8")

    # Persistence is best-effort per report-meta.md §3.1: a failure here
    # MUST NOT invalidate the freshly rendered file.
    async with get_session() as session:
        report_id = await record_report_meta(
            session,
            actor_id,
            model=model,
            title=report_title,
            type=report_type,
            download_path=str(out_path),
        )

    return SkillResult(
        summary={
            "status": "ok",
            "report_path": str(out_path),
            "asset_count": model.summary.asset_count,
            "finding_count": model.summary.finding_count,
            "report_id": report_id,
        }
    )

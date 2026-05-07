"""report-pdf handler."""

from __future__ import annotations

from typing import Any

from secbot.cmdb.db import get_session
from secbot.cmdb.models import DEFAULT_ACTOR
from secbot.report.builder import ReportRenderError, build_report_model
from secbot.report.render import render_pdf
from secbot.skills.types import SkillContext, SkillResult


async def run(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    scan_id: str = args["scan_id"]
    actor_id: str = args.get("actor_id", DEFAULT_ACTOR)

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

    out_path = ctx.scan_dir / "report" / "report.pdf"
    try:
        render_pdf(model, out_path)
    except ReportRenderError as exc:
        return SkillResult(
            summary={
                "status": "error",
                "report_path": None,
                "error": str(exc)[:512],
            }
        )

    return SkillResult(
        summary={
            "status": "ok",
            "report_path": str(out_path),
            "asset_count": model.summary.asset_count,
            "finding_count": model.summary.finding_count,
        }
    )

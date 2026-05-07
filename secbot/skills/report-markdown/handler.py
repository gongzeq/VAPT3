"""report-markdown handler.

Builds the canonical Markdown report into ``<scan_dir>/report/report.md``.
"""

from __future__ import annotations

from typing import Any

from secbot.cmdb.db import get_session
from secbot.cmdb.models import DEFAULT_ACTOR
from secbot.report.builder import build_report_model
from secbot.report.render import render_markdown
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

    md = render_markdown(model)
    report_dir = ctx.scan_dir / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    out_path = report_dir / "report.md"
    out_path.write_text(md, encoding="utf-8")

    return SkillResult(
        summary={
            "status": "ok",
            "report_path": str(out_path),
            "asset_count": model.summary.asset_count,
            "finding_count": model.summary.finding_count,
        }
    )

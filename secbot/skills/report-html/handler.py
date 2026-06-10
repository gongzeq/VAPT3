"""report-html handler.

Renders the canonical HTML report into ``<scan_dir>/report/report.html``.
The HTML format is the single supported export (markdown / pdf / docx were
retired in favour of one canonical deliverable).
"""

from __future__ import annotations

import logging
from typing import Any

from secbot.cmdb.db import get_session
from secbot.cmdb.models import DEFAULT_ACTOR
from secbot.cmdb.repo import create_scan, find_latest_scan_with_assets, get_scan
from secbot.report.builder import build_report_model, record_report_meta
from secbot.report.render import render_html
from secbot.skills.types import SkillContext, SkillResult

_logger = logging.getLogger(__name__)


async def run(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    # scan_id is always inherited from the parent agent loop via
    # bind_skill_context (set in loop.py / subagent.py).  This guarantees
    # the report queries the same CMDB scan record that earlier stages
    # (crawl, vuln_detec, vuln_scan) wrote to via asset_push auto-flush.
    from secbot.agent.tools.skill import current_scan_id
    scan_id: str = current_scan_id()
    actor_id: str = args.get("actor_id", DEFAULT_ACTOR)
    report_title: str = args.get("title") or f"Scan {scan_id} report"
    report_type: str = args.get("type", "custom")
    target: str = args.get("target") or ""

    async with get_session() as session:
        # Ensure the scan row exists so build_report_model never raises.
        # Prior stages may have skipped CMDB writes (e.g. empty results or
        # early failure), but the report must still be renderable.
        scan = await get_scan(session, actor_id, scan_id)
        if scan is None:
            await create_scan(session, actor_id, target=target or report_title or scan_id, scan_id=scan_id)

        model = await build_report_model(session, scan_id, actor_id=actor_id)

        # Fallback: if the current session has no CMDB data (e.g. user
        # requested a report in a new chat for a previously scanned target),
        # search for the most recent historical scan that has assets
        # matching the target.
        if model.is_empty() and target:
            _logger.info(
                "report-html: current scan %r has no assets, searching "
                "historical scans for target=%r",
                scan_id, target,
            )
            hist_scan = await find_latest_scan_with_assets(session, actor_id, target)
            if hist_scan is not None and hist_scan.id != scan_id:
                _logger.info(
                    "report-html: found historical scan %r with assets for target=%r",
                    hist_scan.id, target,
                )
                model = await build_report_model(session, hist_scan.id, actor_id=actor_id)
                # Use the historical scan's target as the report title if
                # the caller didn't supply one explicitly.
                if not args.get("title"):
                    report_title = f"{hist_scan.target} Report"

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


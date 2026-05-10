"""Report model + CMDB→model builder.

See spec §2 (ReportModel schema). All datetimes are UTC.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from secbot.cmdb.models import DEFAULT_ACTOR
from secbot.cmdb.repo import (
    get_scan,
    list_assets,
    list_services,
    list_vulnerabilities,
)

_logger = logging.getLogger(__name__)


SEVERITY_ORDER = ("critical", "high", "medium", "low", "info")


class ReportRenderError(Exception):
    """Raised by render helpers when a template cannot be produced."""


@dataclass(frozen=True)
class ReportFinding:
    severity: str
    category: str
    title: str
    cve_id: Optional[str]
    evidence_summary: Optional[str]
    discovered_by: str


@dataclass(frozen=True)
class ReportService:
    port: int
    protocol: str
    service: Optional[str]
    product: Optional[str]
    version: Optional[str]


@dataclass(frozen=True)
class ReportAsset:
    target: str
    ip: Optional[str]
    hostname: Optional[str]
    os_guess: Optional[str]
    services: list[ReportService] = field(default_factory=list)
    findings: list[ReportFinding] = field(default_factory=list)


@dataclass(frozen=True)
class ReportSummary:
    asset_count: int
    service_count: int
    finding_count: int
    severity_counts: dict[str, int]  # keyed by SEVERITY_ORDER tokens


@dataclass(frozen=True)
class ReportAppendix:
    raw_log_paths: list[str] = field(default_factory=list)
    scope_opt_outs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReportModel:
    scan_id: str
    target: str
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    summary: ReportSummary
    assets: list[ReportAsset]
    appendix: ReportAppendix

    def is_empty(self) -> bool:
        return self.summary.asset_count == 0


async def build_report_model(
    session: AsyncSession,
    scan_id: str,
    *,
    actor_id: str = DEFAULT_ACTOR,
) -> ReportModel:
    """Build a :class:`ReportModel` for *scan_id* by querying the CMDB once."""
    scan = await get_scan(session, actor_id, scan_id)
    if scan is None:
        raise ReportRenderError(
            f"scan {scan_id!r} not found for actor {actor_id!r}"
        )

    assets_rows = await list_assets(session, actor_id, scan_id=scan_id, limit=10_000)

    assets: list[ReportAsset] = []
    severity_counts: dict[str, int] = {s: 0 for s in SEVERITY_ORDER}
    total_services = 0
    total_findings = 0
    raw_logs: list[str] = []

    for asset_row in assets_rows:
        svcs = await list_services(session, actor_id, asset_id=asset_row.id, limit=5000)
        vulns = await list_vulnerabilities(
            session, actor_id, asset_id=asset_row.id, limit=5000
        )
        services = [
            ReportService(
                port=s.port,
                protocol=s.protocol,
                service=s.service,
                product=s.product,
                version=s.version,
            )
            for s in svcs
        ]
        findings = []
        for v in vulns:
            if v.severity in severity_counts:
                severity_counts[v.severity] += 1
            total_findings += 1
            if v.raw_log_path:
                raw_logs.append(v.raw_log_path)
            evidence_summary = None
            if isinstance(v.evidence, dict):
                evidence_summary = (
                    v.evidence.get("summary")
                    or v.evidence.get("matched_at")
                    or str(v.evidence)[:256]
                )
            findings.append(
                ReportFinding(
                    severity=v.severity,
                    category=v.category,
                    title=v.title,
                    cve_id=v.cve_id,
                    evidence_summary=evidence_summary,
                    discovered_by=v.discovered_by,
                )
            )
        total_services += len(services)
        assets.append(
            ReportAsset(
                target=asset_row.target,
                ip=asset_row.ip,
                hostname=asset_row.hostname,
                os_guess=asset_row.os_guess,
                services=services,
                findings=findings,
            )
        )

    summary = ReportSummary(
        asset_count=len(assets),
        service_count=total_services,
        finding_count=total_findings,
        severity_counts=severity_counts,
    )
    appendix = ReportAppendix(
        raw_log_paths=sorted(set(raw_logs)),
        scope_opt_outs=[],
    )
    return ReportModel(
        scan_id=scan.id,
        target=scan.target,
        started_at=scan.started_at,
        finished_at=scan.finished_at,
        summary=summary,
        assets=assets,
        appendix=appendix,
    )


async def record_report_meta(
    session: AsyncSession,
    actor_id: str,
    *,
    model: ReportModel,
    title: str,
    type: str,
    download_path: Optional[str],
    author: Optional[str] = None,
    status: str = "published",
) -> Optional[str]:
    """Best-effort insert into ``report_meta`` after a successful render.

    Contract: `.trellis/spec/backend/report-meta.md` §3.1 — persistence is the
    caller's concern (not ``build_report_model``'s). This helper centralises
    the repo call so each skill handler stays two lines, while matching the
    "log warning, do not roll back the render" rule.

    Returns the generated ``RPT-...`` id on success, or ``None`` when the
    insert fails.
    """

    # Local import avoids a module-load cycle (repo → models → migrations).
    from secbot.cmdb import repo

    critical_count = int(model.summary.severity_counts.get("critical", 0))
    try:
        row = await repo.insert_report_meta(
            session,
            actor_id or DEFAULT_ACTOR,
            scan_id=model.scan_id,
            title=title,
            type=type,
            author=author or actor_id or DEFAULT_ACTOR,
            status=status,
            critical_count=critical_count,
            download_path=download_path,
        )
    except Exception:
        _logger.warning(
            "record_report_meta failed: scan_id=%s title=%r",
            model.scan_id,
            title,
            exc_info=True,
        )
        return None
    return row.id

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


# ---------------------------------------------------------------------------
# Evidence extraction helpers
# ---------------------------------------------------------------------------


def _build_evidence_detail(ev: dict) -> Optional[str]:
    """Compose a human-readable evidence detail from request/response/curl.

    Returns ``None`` when no useful evidence is present.
    """
    parts: list[str] = []
    desc = ev.get("description")
    if desc:
        parts.append(str(desc))
    req = ev.get("request")
    if req:
        parts.append(f"请求:\n{req}" if isinstance(req, str) else f"请求:\n{_trunc(req)}")
    resp = ev.get("response")
    if resp:
        parts.append(f"响应:\n{resp}" if isinstance(resp, str) else f"响应:\n{_trunc(resp)}")
    curl_cmd = ev.get("curl_command") or ev.get("curl")
    if curl_cmd:
        parts.append(f"复现命令:\n{curl_cmd}")
    return "\n\n".join(parts) if parts else None


def _extract_verification_steps(ev: dict) -> tuple[str, ...]:
    """Pull or synthesise verification steps from the evidence dict.

    Priority:
    1. ``verification_steps`` list already present
    2. Synthesise from ``curl_command`` / ``request`` / ``matched_at``
    """
    raw = ev.get("verification_steps") or ev.get("steps")
    if isinstance(raw, list) and raw:
        return tuple(str(s) for s in raw)

    # Synthesise from available evidence
    steps: list[str] = []
    url = ev.get("matched_at") or ev.get("url") or ev.get("endpoint")
    if url:
        steps.append(f"访问目标端点: {url}")
    curl_cmd = ev.get("curl_command") or ev.get("curl")
    if curl_cmd:
        steps.append(f"执行复现命令: {curl_cmd}")
    elif ev.get("request"):
        steps.append("发送构造的 HTTP 请求（见下方证据详情）")
    if ev.get("response"):
        steps.append("检查响应内容以确认漏洞存在")
    return tuple(steps)


def _trunc(value, max_chars: int = 512) -> str:
    """Safely stringify and truncate a value."""
    s = str(value)
    return s if len(s) <= max_chars else s[:max_chars] + "…"


@dataclass(frozen=True)
class ReportFinding:
    severity: str
    category: str
    title: str
    cve_id: Optional[str]
    evidence_summary: Optional[str]
    discovered_by: str
    # Extended fields for professional pentest deliverables.
    affected_url: Optional[str] = None
    evidence_detail: Optional[str] = None
    verification_steps: tuple[str, ...] = ()
    remediation: Optional[str] = None
    references: tuple[str, ...] = ()


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

            # Extract structured evidence fields.  The ``evidence`` JSON
            # column is free-form; we pull well-known keys and gracefully
            # degrade when they are absent.
            ev = v.evidence if isinstance(v.evidence, dict) else {}

            evidence_summary = (
                ev.get("summary")
                or ev.get("matched_at")
                or (str(v.evidence)[:256] if v.evidence else None)
            )
            affected_url = ev.get("matched_at") or ev.get("url") or ev.get("endpoint")

            # Build a detailed evidence blob from request/response/curl
            # when available — this is the core of the "验证步骤" section.
            evidence_detail = _build_evidence_detail(ev)

            # Verification steps: accept a list[str] or synthesise from
            # curl_command / request fields.
            verification_steps = _extract_verification_steps(ev)

            remediation = ev.get("remediation") or ev.get("fix") or ev.get("recommendation")

            refs_raw = ev.get("references") or ev.get("refs") or ()
            references = tuple(refs_raw) if isinstance(refs_raw, (list, tuple)) else ()

            findings.append(
                ReportFinding(
                    severity=v.severity,
                    category=v.category,
                    title=v.title,
                    cve_id=v.cve_id,
                    evidence_summary=evidence_summary,
                    discovered_by=v.discovered_by,
                    affected_url=affected_url,
                    evidence_detail=evidence_detail,
                    verification_steps=verification_steps,
                    remediation=remediation,
                    references=references,
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

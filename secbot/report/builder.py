"""Report model + CMDB→model builder.

See spec §2 (ReportModel schema). All datetimes are UTC.
"""

from __future__ import annotations

import ipaddress
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse

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
_SEVERITY_RANK = {severity: idx for idx, severity in enumerate(SEVERITY_ORDER)}

_CATEGORY_MAP: dict[str, str] = {
    "sqli": "injection",
    "sqli_numeric": "injection",
    "sqli_string": "injection",
    "sqli_search": "injection",
    "sqli_insert": "injection",
    "sqli_boolean_blind": "injection",
    "sql_injection": "injection",
    "nosql_injection": "injection",
    "command_injection": "injection",
    "rce": "injection",
    "ssti": "injection",
    "xxe": "injection",
    "xss": "xss",
    "xss_reflected": "xss",
    "reflected_xss": "xss",
    "xss_stored": "xss",
    "stored_xss": "xss",
    "xss_dom": "xss",
    "dom_xss": "xss",
    "lfi": "exposure",
    "rfi": "exposure",
    "directory_traversal": "exposure",
    "path_traversal": "exposure",
    "git_repo_exposed": "exposure",
    "dockerfile_disclosure": "exposure",
    "info_leak": "exposure",
    "info_disclosure": "exposure",
    "sensitive_data": "exposure",
    "file_upload": "exposure",
    "file_inclusion": "exposure",
    "ssrf": "misconfig",
    "open_redirect": "misconfig",
    "csrf": "misconfig",
    "brute_force": "weak_password",
    "default_credentials": "weak_password",
    "weak_password": "weak_password",
    "broken_auth": "auth",
    "auth_bypass": "auth",
    "idor": "auth",
    "id": "auth",
    "insecure_deserialization": "other",
    "deserialization": "other",
    "php_deserialization": "other",
}


class ReportRenderError(Exception):
    """Raised by render helpers when a template cannot be produced."""


def _normalise_category(raw: object) -> str:
    value = str(raw or "other").strip().lower().replace("-", "_").replace(" ", "_")
    valid = {"injection", "auth", "xss", "misconfig", "exposure", "weak_password", "cve", "other"}
    if value in valid:
        return value
    return _CATEGORY_MAP.get(value, "other")


def _normalise_severity(raw: object, *, confidence: object = None) -> str:
    value = str(raw or "").strip().lower()
    if value in _SEVERITY_RANK:
        return value
    conf = str(confidence or "").strip().lower()
    if conf in {"critical", "high"}:
        return "high"
    if conf in {"medium", "moderate"}:
        return "medium"
    if conf == "low":
        return "low"
    return "info"


def _target_from_url(raw: str) -> str | None:
    try:
        parsed = urlparse(raw)
    except Exception:
        return None
    if not parsed.hostname:
        return None
    if parsed.port and parsed.port not in (80, 443):
        return f"{parsed.hostname}:{parsed.port}"
    return parsed.hostname


def _target_from_payload(payload: dict[str, Any]) -> str | None:
    explicit = payload.get("target") or payload.get("host")
    if explicit:
        return str(explicit)
    url = payload.get("url")
    if isinstance(url, str) and url:
        return _target_from_url(url)
    return None


def _split_target_host(target: str) -> str:
    if "://" in target:
        parsed = urlparse(target)
        return parsed.hostname or target
    parsed = urlparse(f"//{target}")
    return parsed.hostname or target


def _ip_or_hostname(target: str) -> tuple[str | None, str | None]:
    host = _split_target_host(target)
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return None, host or None
    return host, None


def _dt_from_ts(raw: object) -> datetime | None:
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw, tz=timezone.utc)
    return None


def _evidence_text(payload: dict[str, Any]) -> str | None:
    evidence = payload.get("evidence")
    if isinstance(evidence, str) and evidence.strip():
        return evidence.strip()
    if evidence:
        return _trunc(evidence)
    return None


def _finding_title(payload: dict[str, Any], affected_url: str | None) -> str:
    if payload.get("title"):
        return str(payload["title"])
    raw_type = str(payload.get("type") or payload.get("category") or "vulnerability")
    if affected_url:
        return f"{raw_type} on {affected_url}"
    return raw_type


def _finding_detail(payload: dict[str, Any]) -> str | None:
    parts: list[str] = []
    for label, key in (
        ("参数", "param"),
        ("Payload", "payload"),
        ("DBMS", "dbms"),
        ("状态", "status"),
        ("证据", "evidence"),
    ):
        value = payload.get(key)
        if value:
            parts.append(f"{label}: {value}")
    return "\n".join(parts) if parts else None


def _verification_steps(payload: dict[str, Any], affected_url: str | None) -> tuple[str, ...]:
    raw_steps = payload.get("verification_steps") or payload.get("steps")
    if isinstance(raw_steps, list) and raw_steps:
        return tuple(str(step) for step in raw_steps)
    steps: list[str] = []
    if affected_url:
        steps.append(f"访问目标端点: {affected_url}")
    if payload.get("param"):
        steps.append(f"对参数 {payload['param']} 发送测试载荷")
    if payload.get("payload"):
        steps.append(f"使用载荷: {payload['payload']}")
    if payload.get("evidence"):
        steps.append("根据响应内容或工具输出确认漏洞存在")
    return tuple(steps)


# ---------------------------------------------------------------------------
# Evidence extraction helpers
# ---------------------------------------------------------------------------


def _build_evidence_detail(ev: dict) -> Optional[str]:
    """Compose a human-readable evidence detail from structured PoC data.

    Extracts and formats request/response/curl/payload/matched_at fields
    into a readable PoC section for the report.
    Returns ``None`` when no useful evidence is present.
    """
    parts: list[str] = []

    # Handle legacy {"raw": "..."} format — promote raw to description
    if "raw" in ev and not ev.get("description"):
        raw = ev["raw"]
        if isinstance(raw, str) and raw.strip():
            ev = dict(ev)
            ev.setdefault("description", raw.strip())

    desc = ev.get("description")
    if desc:
        parts.append(f"漏洞描述: {desc}")

    matched = ev.get("matched_at") or ev.get("url") or ev.get("endpoint")
    if matched:
        parts.append(f"匹配位置: {matched}")

    payload_val = ev.get("payload")
    if payload_val:
        parts.append(f"攻击载荷: {payload_val}")

    req = ev.get("request")
    if req:
        parts.append(
            f"PoC 请求:\n{_trunc_evidence(req)}" if isinstance(req, str)
            else f"PoC 请求:\n{_trunc_evidence(req)}"
        )

    resp = ev.get("response")
    if resp:
        parts.append(
            f"系统响应 (证据):\n{_trunc_evidence(resp)}" if isinstance(resp, str)
            else f"系统响应 (证据):\n{_trunc_evidence(resp)}"
        )

    curl_cmd = ev.get("curl_command") or ev.get("curl")
    if curl_cmd:
        parts.append(f"复现命令:\n{curl_cmd}")

    return "\n\n".join(parts) if parts else None


def _extract_verification_steps(ev: dict) -> tuple[str, ...]:
    """Pull or synthesise verification steps from the evidence dict.

    Priority:
    1. ``verification_steps`` list already present
    2. Synthesise from ``curl_command`` / ``request`` / ``matched_at`` / ``payload``
    """
    raw = ev.get("verification_steps") or ev.get("steps")
    if isinstance(raw, list) and raw:
        return tuple(str(s) for s in raw)

    # Synthesise from available evidence
    steps: list[str] = []
    url = ev.get("matched_at") or ev.get("url") or ev.get("endpoint")
    if url:
        steps.append(f"访问目标端点: {url}")
    payload_val = ev.get("payload")
    if payload_val:
        steps.append(f"构造并发送攻击载荷: {payload_val}")
    curl_cmd = ev.get("curl_command") or ev.get("curl")
    if curl_cmd:
        steps.append(f"执行复现命令: {curl_cmd}")
    elif ev.get("request"):
        steps.append("发送构造的 HTTP 请求（见下方 PoC 请求）")
    if ev.get("response"):
        steps.append("检查系统响应内容以确认漏洞存在（见下方系统响应）")
    return tuple(steps)


def _trunc(value, max_chars: int = 512) -> str:
    """Safely stringify and truncate a value."""
    s = str(value)
    return s if len(s) <= max_chars else s[:max_chars] + "…"


def _trunc_evidence(value, max_chars: int = 2048) -> str:
    """Safely stringify and truncate evidence content (larger limit for PoC)."""
    s = str(value)
    return s if len(s) <= max_chars else s[:max_chars] + "…(truncated)"


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
    # Raw evidence dict for structured PoC rendering in HTML.
    evidence_raw: Optional[dict] = None


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


def merge_report_models(
    primary: ReportModel,
    secondary: ReportModel,
) -> ReportModel:
    """Merge two report models while de-duplicating assets and findings.

    The primary model wins for top-level target wording and conflicting
    asset metadata. This lets report-html combine the structured
    VulnerabilityStore with session JSONL / AssetFeed discoveries instead of
    treating either source as exclusive.
    """
    if primary.is_empty():
        return secondary
    if secondary.is_empty():
        return primary

    assets_by_target: dict[str, ReportAsset] = {}

    def _merge_asset(incoming: ReportAsset) -> None:
        existing = assets_by_target.get(incoming.target)
        if existing is None:
            assets_by_target[incoming.target] = ReportAsset(
                target=incoming.target,
                ip=incoming.ip,
                hostname=incoming.hostname,
                os_guess=incoming.os_guess,
                services=list(incoming.services),
                findings=list(incoming.findings),
            )
            return

        services_by_key = {
            (service.port, service.protocol): service for service in existing.services
        }
        for service in incoming.services:
            services_by_key.setdefault((service.port, service.protocol), service)

        finding_keys = {_finding_dedupe_key(finding) for finding in existing.findings}
        findings = list(existing.findings)
        for finding in incoming.findings:
            key = _finding_dedupe_key(finding)
            if key in finding_keys:
                continue
            finding_keys.add(key)
            findings.append(finding)

        assets_by_target[incoming.target] = ReportAsset(
            target=existing.target,
            ip=existing.ip or incoming.ip,
            hostname=existing.hostname or incoming.hostname,
            os_guess=existing.os_guess or incoming.os_guess,
            services=sorted(
                services_by_key.values(),
                key=lambda service: (service.protocol, service.port),
            ),
            findings=sorted(
                findings,
                key=lambda finding: _SEVERITY_RANK.get(
                    finding.severity, len(SEVERITY_ORDER)
                ),
            ),
        )

    for model in (primary, secondary):
        for asset in model.assets:
            _merge_asset(asset)

    assets = sorted(assets_by_target.values(), key=lambda asset: asset.target)
    severity_counts: dict[str, int] = {severity: 0 for severity in SEVERITY_ORDER}
    service_count = 0
    finding_count = 0
    for asset in assets:
        service_count += len(asset.services)
        finding_count += len(asset.findings)
        for finding in asset.findings:
            if finding.severity in severity_counts:
                severity_counts[finding.severity] += 1

    return ReportModel(
        scan_id=primary.scan_id,
        target=primary.target or secondary.target,
        started_at=_min_dt(primary.started_at, secondary.started_at),
        finished_at=_max_dt(primary.finished_at, secondary.finished_at),
        summary=ReportSummary(
            asset_count=len(assets),
            service_count=service_count,
            finding_count=finding_count,
            severity_counts=severity_counts,
        ),
        assets=assets,
        appendix=ReportAppendix(
            raw_log_paths=_dedupe_strs(
                primary.appendix.raw_log_paths + secondary.appendix.raw_log_paths
            ),
            scope_opt_outs=_dedupe_strs(
                primary.appendix.scope_opt_outs + secondary.appendix.scope_opt_outs
            ),
        ),
    )


def _finding_dedupe_key(finding: ReportFinding) -> tuple[str, str, str, str, str]:
    return (
        finding.title.strip().lower(),
        finding.severity,
        (finding.affected_url or "").strip().lower(),
        (finding.cve_id or "").strip().lower(),
        (finding.evidence_summary or "").strip().lower()[:160],
    )


def _min_dt(a: datetime | None, b: datetime | None) -> datetime | None:
    if a is None:
        return b
    if b is None:
        return a
    return min(a, b)


def _max_dt(a: datetime | None, b: datetime | None) -> datetime | None:
    if a is None:
        return b
    if b is None:
        return a
    return max(a, b)


def _dedupe_strs(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


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
                ev.get("description")
                or ev.get("summary")
                or ev.get("raw")
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
                    evidence_raw=ev if ev else None,
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


def build_report_model_from_asset_entries(
    entries: list[dict[str, Any]],
    *,
    scan_id: str,
    target: str | None = None,
) -> ReportModel:
    """Build a report model from transient asset-feed entries.

    This is a read-only fallback for sessions where scan discoveries were
    deliberately kept out of the CMDB by the Asset Auto-Management gate.
    """
    assets_by_target: dict[str, dict[str, Any]] = {}
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def _asset_state(asset_target: str) -> dict[str, Any]:
        ip, hostname = _ip_or_hostname(asset_target)
        state = assets_by_target.get(asset_target)
        if state is None:
            state = {
                "target": asset_target,
                "ip": ip,
                "hostname": hostname,
                "os_guess": None,
                "services": {},
                "findings": [],
            }
            assets_by_target[asset_target] = state
        return state

    for entry in sorted(entries, key=lambda item: item.get("id", 0)):
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            continue
        created_at = _dt_from_ts(entry.get("created_at"))
        if created_at is not None:
            started_at = created_at if started_at is None else min(started_at, created_at)
            finished_at = created_at if finished_at is None else max(finished_at, created_at)

        kind = str(entry.get("kind", "")).lower()
        asset_target = _target_from_payload(payload) or target
        if not asset_target:
            continue
        state = _asset_state(str(asset_target))

        if kind == "tech":
            os_guess = payload.get("os") or payload.get("os_guess")
            if os_guess and not state["os_guess"]:
                state["os_guess"] = str(os_guess)
            continue

        if kind in {"port", "service"} and payload.get("port") is not None:
            try:
                port = int(payload["port"])
            except (TypeError, ValueError):
                continue
            protocol = str(payload.get("protocol") or "tcp")
            state["services"][(port, protocol)] = ReportService(
                port=port,
                protocol=protocol,
                service=payload.get("service"),
                product=payload.get("product"),
                version=payload.get("version"),
            )
            continue

        if kind == "vuln":
            affected_url = payload.get("url")
            affected_url = str(affected_url) if affected_url else None
            severity = _normalise_severity(
                payload.get("severity"),
                confidence=payload.get("confidence"),
            )
            ev_summary = _evidence_text(payload)
            detail = _finding_detail(payload)
            if detail is None and ev_summary:
                detail = ev_summary
            # Build evidence_raw dict for structured PoC rendering
            ev_raw = payload.get("evidence")
            if isinstance(ev_raw, dict):
                evidence_raw = ev_raw
            elif isinstance(ev_raw, str) and ev_raw.strip():
                evidence_raw = {"description": ev_raw.strip()}
            else:
                evidence_raw = None
            # Augment ev_raw with top-level fields if available
            if evidence_raw is not None:
                for _k in ("request", "response", "curl_command", "payload", "matched_at"):
                    if _k not in evidence_raw and payload.get(_k):
                        evidence_raw[_k] = payload[_k]
            state["findings"].append(
                ReportFinding(
                    severity=severity,
                    category=_normalise_category(payload.get("type") or payload.get("category")),
                    title=_finding_title(payload, affected_url),
                    cve_id=payload.get("cve_id") or None,
                    evidence_summary=ev_summary,
                    discovered_by=str(entry.get("agent_name") or "asset_feed"),
                    affected_url=affected_url,
                    evidence_detail=detail,
                    verification_steps=_verification_steps(payload, affected_url),
                    remediation=payload.get("remediation")
                    or payload.get("fix")
                    or payload.get("recommendation"),
                    references=tuple(payload.get("references") or ()),
                    evidence_raw=evidence_raw,
                )
            )

    assets: list[ReportAsset] = []
    severity_counts: dict[str, int] = {severity: 0 for severity in SEVERITY_ORDER}
    service_count = 0
    finding_count = 0
    for state in assets_by_target.values():
        services = sorted(
            state["services"].values(),
            key=lambda service: (service.protocol, service.port),
        )
        findings = sorted(
            state["findings"],
            key=lambda finding: _SEVERITY_RANK.get(finding.severity, len(SEVERITY_ORDER)),
        )
        for finding in findings:
            if finding.severity in severity_counts:
                severity_counts[finding.severity] += 1
        service_count += len(services)
        finding_count += len(findings)
        assets.append(
            ReportAsset(
                target=state["target"],
                ip=state["ip"],
                hostname=state["hostname"],
                os_guess=state["os_guess"],
                services=services,
                findings=findings,
            )
        )

    assets.sort(key=lambda asset: asset.target)
    summary = ReportSummary(
        asset_count=len(assets),
        service_count=service_count,
        finding_count=finding_count,
        severity_counts=severity_counts,
    )
    return ReportModel(
        scan_id=scan_id,
        target=target or (assets[0].target if assets else scan_id),
        started_at=started_at,
        finished_at=finished_at,
        summary=summary,
        assets=assets,
        appendix=ReportAppendix(),
    )


def build_report_model_from_vulnerabilities(
    entries: list[dict[str, Any]],
    *,
    scan_id: str,
    target: str | None = None,
) -> ReportModel:
    """Build a :class:`ReportModel` from VulnerabilityStore entries.

    Each entry is a dict with the VulnerabilityEntry schema (title,
    severity, description, exploitation_proof, verification_method,
    cvss, endpoint, poc_description, poc_script_code, remediation_steps).
    """
    assets_by_target: dict[str, dict[str, Any]] = {}
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def _asset_state(asset_target: str) -> dict[str, Any]:
        ip, hostname = _ip_or_hostname(asset_target)
        state = assets_by_target.get(asset_target)
        if state is None:
            state = {
                "target": asset_target,
                "ip": ip,
                "hostname": hostname,
                "os_guess": None,
                "services": {},
                "findings": [],
            }
            assets_by_target[asset_target] = state
        return state

    for entry in sorted(entries, key=lambda item: item.get("id", 0)):
        created_at = _dt_from_ts(entry.get("created_at"))
        if created_at is not None:
            started_at = created_at if started_at is None else min(started_at, created_at)
            finished_at = created_at if finished_at is None else max(finished_at, created_at)

        endpoint = entry.get("endpoint") or ""
        asset_target = _target_from_url(endpoint) if endpoint else None
        asset_target = asset_target or target or "unknown"
        state = _asset_state(str(asset_target))

        severity = _normalise_severity(entry.get("severity"))
        title = entry.get("title") or "Unknown vulnerability"
        description = entry.get("description") or ""
        exploitation_proof = entry.get("exploitation_proof") or ""
        verification_method = entry.get("verification_method") or ""
        cvss = entry.get("cvss")

        # Build evidence_detail from the structured fields.
        evidence_parts: list[str] = []
        if description:
            evidence_parts.append(f"Description: {description}")
        if verification_method:
            evidence_parts.append(f"Verification method: {verification_method}")
        if cvss is not None:
            evidence_parts.append(f"CVSS: {cvss}")
        if exploitation_proof:
            evidence_parts.append(f"Exploitation proof:\n{_trunc_evidence(exploitation_proof)}")
        poc_desc = entry.get("poc_description")
        if poc_desc:
            evidence_parts.append(f"PoC description: {poc_desc}")
        poc_code = entry.get("poc_script_code")
        if poc_code:
            evidence_parts.append(f"PoC script:\n{_trunc_evidence(poc_code)}")
        evidence_detail = "\n\n".join(evidence_parts) if evidence_parts else None

        # Build evidence_raw dict for structured PoC rendering.
        evidence_raw: dict[str, Any] = {
            "description": description,
        }
        if exploitation_proof:
            evidence_raw["response"] = exploitation_proof
        if poc_code:
            evidence_raw["curl_command"] = poc_code
        if endpoint:
            evidence_raw["matched_at"] = endpoint
        if poc_desc:
            evidence_raw["payload"] = poc_desc

        # Synthesise verification_steps from the available data.
        verification_steps: list[str] = []
        if endpoint:
            verification_steps.append(f"Access endpoint: {endpoint}")
        if exploitation_proof:
            verification_steps.append("Review exploitation proof below")
        if poc_code:
            verification_steps.append(f"Run PoC script: {poc_code[:80]}")

        remediation = entry.get("remediation_steps")

        state["findings"].append(
            ReportFinding(
                severity=severity,
                category=_normalise_category(
                    entry.get("category") or entry.get("type") or "other"
                ),
                title=title,
                cve_id=entry.get("cve_id"),
                evidence_summary=exploitation_proof[:256] if exploitation_proof else description[:256],
                discovered_by=str(entry.get("agent_name") or "vulnerability_store"),
                affected_url=endpoint or None,
                evidence_detail=evidence_detail,
                verification_steps=tuple(verification_steps),
                remediation=remediation,
                references=(),
                evidence_raw=evidence_raw,
            )
        )

    assets: list[ReportAsset] = []
    severity_counts: dict[str, int] = {severity: 0 for severity in SEVERITY_ORDER}
    service_count = 0
    finding_count = 0
    for state in assets_by_target.values():
        services = sorted(
            state["services"].values(),
            key=lambda service: (service.protocol, service.port),
        )
        findings = sorted(
            state["findings"],
            key=lambda finding: _SEVERITY_RANK.get(finding.severity, len(SEVERITY_ORDER)),
        )
        for finding in findings:
            if finding.severity in severity_counts:
                severity_counts[finding.severity] += 1
        service_count += len(services)
        finding_count += len(findings)
        assets.append(
            ReportAsset(
                target=state["target"],
                ip=state["ip"],
                hostname=state["hostname"],
                os_guess=state["os_guess"],
                services=services,
                findings=findings,
            )
        )

    assets.sort(key=lambda asset: asset.target)
    summary = ReportSummary(
        asset_count=len(assets),
        service_count=service_count,
        finding_count=finding_count,
        severity_counts=severity_counts,
    )
    return ReportModel(
        scan_id=scan_id,
        target=target or (assets[0].target if assets else scan_id),
        started_at=started_at,
        finished_at=finished_at,
        summary=summary,
        assets=assets,
        appendix=ReportAppendix(),
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

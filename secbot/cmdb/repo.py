"""Repository helpers for the CMDB.

Hard rules (per `.trellis/spec/backend/cmdb-schema.md` §3 + §4):

- ``actor_id`` is the **first** positional argument of every helper. Reads MUST
  filter by it; writes MUST stamp it.
- Upserts are keyed on natural keys so re-scans are idempotent:
    * asset:        ``(actor_id, scan_id, target)`` — re-scans bind to scan
    * service:      ``(asset_id, port, protocol)``
    * vulnerability: ``(asset_id, service_id, title, cve_id)``
- All helpers take a live :class:`AsyncSession`. They do **not** open or commit
  sessions; the caller owns the transaction (use :func:`secbot.cmdb.db.get_session`).
"""

from __future__ import annotations

import ipaddress
import logging
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional, Sequence
from urllib.parse import urlparse

from sqlalchemy import case, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from secbot.cmdb.models import (
    DEFAULT_ACTOR,
    REPORT_STATUS_TRANSITIONS,
    VALID_ASSET_TYPES,
    VALID_REPORT_STATUSES,
    VALID_REPORT_TYPES,
    VALID_SCAN_STATUSES,
    VALID_SEVERITIES,
    VALID_VULN_CANDIDATE_STATUSES,
    VALID_VULN_CATEGORIES,
    Asset,
    ReportMeta,
    Scan,
    Service,
    Vulnerability,
    VulnerabilityCandidate,
)

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ULID (Crockford base32, 26 chars) — small standalone implementation so we
# don't introduce a third-party dep just for IDs.
# ---------------------------------------------------------------------------

_ULID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_ulid() -> str:
    ts_ms = int(time.time() * 1000)
    rand = secrets.randbits(80)
    encoded: list[str] = []
    n = ts_ms
    for _ in range(10):
        encoded.append(_ULID_ALPHABET[n & 0x1F])
        n >>= 5
    n = rand
    for _ in range(16):
        encoded.append(_ULID_ALPHABET[n & 0x1F])
        n >>= 5
    return "".join(reversed(encoded))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


_HOST_PORT_RE = re.compile(r"^\[?([A-Fa-f0-9:.]+)\]?:(\d{1,5})$")


def _normalise_host_token(value: str | None) -> str | None:
    """Return a lowercase host/IP token stripped of URL, path, and port noise."""

    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None

    parsed = urlparse(raw if "://" in raw else f"//{raw}")
    host = parsed.hostname
    if not host:
        match = _HOST_PORT_RE.match(raw)
        host = match.group(1) if match else raw.split("/", 1)[0]
    host = host.strip("[] ").rstrip(".").lower()
    return host or None


def _normalise_ip(value: str | None) -> str | None:
    token = _normalise_host_token(value)
    if not token:
        return None
    try:
        return str(ipaddress.ip_address(token))
    except ValueError:
        return None


def _normalise_hostname(value: str | None) -> str | None:
    token = _normalise_host_token(value)
    if token is None:
        return None
    if _normalise_ip(token) is not None:
        return None
    return token


def _merge_asset_tags(
    existing: dict[str, Any] | None,
    incoming: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Merge automatic asset tags while preserving existing governance keys."""

    if existing is None and incoming is None:
        return None
    merged: dict[str, Any] = dict(existing or {})
    for key, value in (incoming or {}).items():
        if key in {"system", "type"} and merged.get(key):
            continue
        merged[key] = value
    return merged


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------


async def create_scan(
    session: AsyncSession,
    actor_id: str,
    *,
    target: str,
    scope: Optional[dict[str, Any]] = None,
    scan_id: Optional[str] = None,
) -> Scan:
    scan = Scan(
        id=scan_id or new_ulid(),
        target=target,
        status="queued",
        scope_json=scope,
        actor_id=actor_id or DEFAULT_ACTOR,
    )
    session.add(scan)
    await session.flush()
    return scan


async def get_scan(session: AsyncSession, actor_id: str, scan_id: str) -> Optional[Scan]:
    stmt = select(Scan).where(Scan.actor_id == actor_id, Scan.id == scan_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_scans(
    session: AsyncSession,
    actor_id: str,
    *,
    status: Optional[str] = None,
    limit: int = 50,
) -> Sequence[Scan]:
    stmt = select(Scan).where(Scan.actor_id == actor_id)
    if status is not None:
        if status not in VALID_SCAN_STATUSES:
            raise ValueError(f"unknown scan status: {status!r}")
        stmt = stmt.where(Scan.status == status)
    stmt = stmt.order_by(Scan.created_at.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars().all())


async def update_scan_status(
    session: AsyncSession,
    actor_id: str,
    scan_id: str,
    *,
    status: str,
    error: Optional[str] = None,
) -> Scan:
    if status not in VALID_SCAN_STATUSES:
        raise ValueError(f"unknown scan status: {status!r}")

    scan = await get_scan(session, actor_id, scan_id)
    if scan is None:
        raise LookupError(f"scan {scan_id!r} not found for actor {actor_id!r}")

    now = _utcnow()
    scan.status = status
    if status == "running" and scan.started_at is None:
        scan.started_at = now
    if status in {"completed", "failed", "cancelled"}:
        scan.finished_at = now
    if status == "failed":
        scan.error = error
    await session.flush()
    return scan


# ---------------------------------------------------------------------------
# Asset
# ---------------------------------------------------------------------------


async def upsert_asset(
    session: AsyncSession,
    actor_id: str,
    *,
    scan_id: str,
    target: str,
    ip: Optional[str] = None,
    hostname: Optional[str] = None,
    os_guess: Optional[str] = None,
    tags: Optional[dict[str, Any]] = None,
) -> Asset:
    """Insert-or-update an asset keyed by normalized host identity.

    The same real IP/hostname discovered by multiple scans MUST resolve to one
    Managed Asset. ``scan_id`` remains the first-discovery scan for the row.

    ``tags`` is a JSON object. Reserved keys per
    `.trellis/spec/backend/cmdb-schema.md` §2.1.1:

    - ``system`` — business system name (e.g. ``"CRM"``), used by
      ``/api/dashboard/asset-cluster``.
    - ``type`` — one of :data:`~secbot.cmdb.models.VALID_ASSET_TYPES`, used by
      ``/api/dashboard/asset-distribution``.
    """

    actor = actor_id or DEFAULT_ACTOR
    norm_ip = _normalise_ip(ip) or _normalise_ip(target)
    norm_hostname = (
        _normalise_hostname(hostname)
        or _normalise_hostname(target)
        or None
    )
    norm_target = _normalise_host_token(target) or target

    identity_queries = []
    if norm_ip is not None:
        identity_queries.append(select(Asset).where(Asset.actor_id == actor, Asset.ip == norm_ip))
    if norm_hostname is not None:
        identity_queries.append(
            select(Asset).where(
                Asset.actor_id == actor,
                (
                    (func.lower(Asset.hostname) == norm_hostname)
                    | (func.lower(Asset.target) == norm_hostname)
                ),
            )
        )
    identity_queries.append(
        select(Asset).where(
            Asset.actor_id == actor,
            func.lower(Asset.target) == str(norm_target).lower(),
        )
    )

    asset = None
    for stmt in identity_queries:
        asset = (await session.execute(stmt.limit(1))).scalar_one_or_none()
        if asset is not None:
            break

    if asset is None:
        asset = Asset(
            actor_id=actor,
            scan_id=scan_id,
            target=norm_target,
            ip=norm_ip,
            hostname=norm_hostname,
            os_guess=os_guess,
            tags=dict(tags) if tags else None,
        )
        session.add(asset)
    else:
        if norm_ip is not None:
            asset.ip = norm_ip
        if norm_hostname is not None:
            asset.hostname = norm_hostname
        if os_guess is not None:
            asset.os_guess = os_guess
        if tags is not None:
            asset.tags = _merge_asset_tags(asset.tags, tags)
        asset.updated_at = _utcnow()

    await session.flush()
    return asset


async def list_assets(
    session: AsyncSession,
    actor_id: str,
    *,
    scan_id: Optional[str] = None,
    limit: int = 200,
) -> Sequence[Asset]:
    stmt = select(Asset).where(Asset.actor_id == actor_id)
    if scan_id is not None:
        stmt = stmt.where(Asset.scan_id == scan_id)
    stmt = stmt.order_by(Asset.id.asc()).limit(limit)
    return list((await session.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


async def upsert_service(
    session: AsyncSession,
    actor_id: str,
    *,
    asset_id: int,
    port: int,
    protocol: str,
    state: str = "open",
    service: Optional[str] = None,
    product: Optional[str] = None,
    version: Optional[str] = None,
) -> Service:
    """Upsert a service keyed on ``(asset_id, port, protocol)``."""

    if protocol not in {"tcp", "udp"}:
        raise ValueError(f"protocol must be tcp or udp, got {protocol!r}")

    stmt = select(Service).where(
        Service.actor_id == actor_id,
        Service.asset_id == asset_id,
        Service.port == port,
        Service.protocol == protocol,
    )
    svc = (await session.execute(stmt)).scalar_one_or_none()

    if svc is None:
        svc = Service(
            actor_id=actor_id or DEFAULT_ACTOR,
            asset_id=asset_id,
            port=port,
            protocol=protocol,
            state=state,
            service=service,
            product=product,
            version=version,
        )
        session.add(svc)
    else:
        svc.state = state
        if service is not None:
            svc.service = service
        if product is not None:
            svc.product = product
        if version is not None:
            svc.version = version
        svc.updated_at = _utcnow()

    await session.flush()
    return svc


async def list_services(
    session: AsyncSession,
    actor_id: str,
    *,
    asset_id: Optional[int] = None,
    limit: int = 500,
) -> Sequence[Service]:
    stmt = select(Service).where(Service.actor_id == actor_id)
    if asset_id is not None:
        stmt = stmt.where(Service.asset_id == asset_id)
    stmt = stmt.order_by(Service.asset_id.asc(), Service.port.asc()).limit(limit)
    return list((await session.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# Vulnerability
# ---------------------------------------------------------------------------


async def upsert_vulnerability(
    session: AsyncSession,
    actor_id: str,
    *,
    asset_id: int,
    severity: str,
    category: str,
    title: str,
    discovered_by: str,
    service_id: Optional[int] = None,
    cve_id: Optional[str] = None,
    evidence: Optional[dict[str, Any]] = None,
    raw_log_path: Optional[str] = None,
) -> Vulnerability:
    """Upsert a vulnerability keyed on ``(asset_id, service_id, title, cve_id)``.

    Re-running a scan that re-discovers the same finding MUST refresh
    ``evidence`` / ``raw_log_path`` instead of duplicating the row.
    """

    if severity not in VALID_SEVERITIES:
        raise ValueError(f"invalid severity {severity!r}; expected one of {sorted(VALID_SEVERITIES)}")
    if category not in VALID_VULN_CATEGORIES:
        raise ValueError(
            f"invalid category {category!r}; expected one of {sorted(VALID_VULN_CATEGORIES)}"
        )

    stmt = select(Vulnerability).where(
        Vulnerability.actor_id == actor_id,
        Vulnerability.asset_id == asset_id,
        Vulnerability.title == title,
    )
    if service_id is None:
        stmt = stmt.where(Vulnerability.service_id.is_(None))
    else:
        stmt = stmt.where(Vulnerability.service_id == service_id)
    if cve_id is None:
        stmt = stmt.where(Vulnerability.cve_id.is_(None))
    else:
        stmt = stmt.where(Vulnerability.cve_id == cve_id)

    vuln = (await session.execute(stmt)).scalar_one_or_none()

    if vuln is None:
        was_critical = False
        vuln = Vulnerability(
            actor_id=actor_id or DEFAULT_ACTOR,
            asset_id=asset_id,
            service_id=service_id,
            severity=severity,
            category=category,
            title=title,
            cve_id=cve_id,
            evidence=evidence,
            raw_log_path=raw_log_path,
            discovered_by=discovered_by,
        )
        session.add(vuln)
    else:
        was_critical = vuln.severity == "critical"
        vuln.severity = severity
        vuln.category = category
        vuln.discovered_by = discovered_by
        if evidence is not None:
            vuln.evidence = evidence
        if raw_log_path is not None:
            vuln.raw_log_path = raw_log_path

    await session.flush()

    # Surface newly-discovered or newly-escalated critical findings to the
    # notification center. Re-scans that re-confirm an already-critical finding
    # stay silent to avoid notification spam (PRD 05-10-p2 §通知源 — "高危
    # 漏洞新增"). Late-import keeps cmdb.repo free of a channels dependency at
    # import time (channels.notifications itself imports cmdb.repo.new_ulid).
    if severity == "critical" and not was_critical:
        try:
            from secbot.channels.notifications import get_notification_queue

            get_notification_queue().publish(
                type="critical_vuln",
                title=f"高危漏洞：{title}",
                body=f"asset_id={asset_id} category={category}",
            )
        except Exception:  # pragma: no cover - defensive: notification is non-critical
            _logger.warning("critical_vuln notification publish failed", exc_info=True)

    return vuln


async def list_vulnerabilities(
    session: AsyncSession,
    actor_id: str,
    *,
    asset_id: Optional[int] = None,
    severity_in: Optional[Iterable[str]] = None,
    limit: int = 500,
) -> Sequence[Vulnerability]:
    stmt = select(Vulnerability).where(Vulnerability.actor_id == actor_id)
    if asset_id is not None:
        stmt = stmt.where(Vulnerability.asset_id == asset_id)
    if severity_in is not None:
        sevs = list(severity_in)
        for s in sevs:
            if s not in VALID_SEVERITIES:
                raise ValueError(f"invalid severity in filter: {s!r}")
        stmt = stmt.where(Vulnerability.severity.in_(sevs))
    stmt = stmt.order_by(Vulnerability.created_at.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# Vulnerability candidates
# ---------------------------------------------------------------------------


def vulnerability_identity_key(
    *,
    cve_id: str | None = None,
    cnvd_id: str | None = None,
    category: str = "other",
    title: str = "",
) -> str:
    """Return a stable vulnerability identity key, merging common aliases."""

    cve = (cve_id or "").strip().upper()
    if cve:
        return f"CVE:{cve}"
    cnvd = (cnvd_id or "").strip().upper()
    if cnvd:
        return f"CNVD:{cnvd}"
    normalized_title = re.sub(r"\s+", " ", (title or "unknown").strip().lower())
    normalized_title = re.sub(r"[^a-z0-9\u4e00-\u9fff _.-]+", "", normalized_title)
    return f"TITLE:{category}:{normalized_title or 'unknown'}"


async def upsert_vulnerability_candidate(
    session: AsyncSession,
    actor_id: str,
    *,
    asset_id: int,
    category: str,
    title: str,
    source: str,
    service_id: Optional[int] = None,
    identity_key: Optional[str] = None,
    cve_id: Optional[str] = None,
    cnvd_id: Optional[str] = None,
    evidence: Optional[dict[str, Any]] = None,
    status: str = "candidate",
    last_verification_error: Optional[str] = None,
) -> VulnerabilityCandidate:
    """Insert or update a passive vulnerability match.

    Candidates are not confirmed findings and must not be counted by dashboard
    vulnerability KPIs until explicit verification succeeds.
    """

    actor = actor_id or DEFAULT_ACTOR
    if category not in VALID_VULN_CATEGORIES:
        raise ValueError(
            f"invalid category {category!r}; expected one of {sorted(VALID_VULN_CATEGORIES)}"
        )
    if status not in VALID_VULN_CANDIDATE_STATUSES:
        raise ValueError(
            "invalid candidate status "
            f"{status!r}; expected one of {sorted(VALID_VULN_CANDIDATE_STATUSES)}"
        )
    key = identity_key or vulnerability_identity_key(
        cve_id=cve_id,
        cnvd_id=cnvd_id,
        category=category,
        title=title,
    )

    stmt = select(VulnerabilityCandidate).where(
        VulnerabilityCandidate.actor_id == actor,
        VulnerabilityCandidate.asset_id == asset_id,
        VulnerabilityCandidate.identity_key == key,
    )
    if service_id is None:
        stmt = stmt.where(VulnerabilityCandidate.service_id.is_(None))
    else:
        stmt = stmt.where(VulnerabilityCandidate.service_id == service_id)
    row = (await session.execute(stmt)).scalar_one_or_none()

    if row is None:
        row = VulnerabilityCandidate(
            actor_id=actor,
            asset_id=asset_id,
            service_id=service_id,
            identity_key=key,
            cve_id=cve_id,
            cnvd_id=cnvd_id,
            category=category,
            title=title,
            source=source,
            evidence=evidence,
            status=status,
            last_verification_error=last_verification_error,
        )
        session.add(row)
    else:
        row.cve_id = cve_id
        row.cnvd_id = cnvd_id
        row.category = category
        row.title = title
        row.source = source
        if evidence is not None:
            row.evidence = evidence
        row.status = status
        row.last_verification_error = last_verification_error
        row.updated_at = _utcnow()

    await session.flush()
    return row


async def list_vulnerability_candidates(
    session: AsyncSession,
    actor_id: str,
    *,
    status: Optional[str] = None,
    asset_id: Optional[int] = None,
    include_dismissed: bool = False,
    limit: int = 500,
) -> Sequence[VulnerabilityCandidate]:
    """List passive vulnerability candidates for asset detail/topology views."""

    if status is not None and status not in VALID_VULN_CANDIDATE_STATUSES:
        raise ValueError(
            "invalid candidate status "
            f"{status!r}; expected one of {sorted(VALID_VULN_CANDIDATE_STATUSES)}"
        )
    stmt = select(VulnerabilityCandidate).where(VulnerabilityCandidate.actor_id == actor_id)
    if asset_id is not None:
        stmt = stmt.where(VulnerabilityCandidate.asset_id == asset_id)
    if status is not None:
        stmt = stmt.where(VulnerabilityCandidate.status == status)
    elif not include_dismissed:
        stmt = stmt.where(VulnerabilityCandidate.status != "dismissed")
    stmt = stmt.order_by(VulnerabilityCandidate.updated_at.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars().all())


async def mark_candidate_verification_failed(
    session: AsyncSession,
    actor_id: str,
    candidate_id: int,
    *,
    error: str,
) -> VulnerabilityCandidate:
    """Record failed verification evidence without dismissing the candidate."""

    stmt = select(VulnerabilityCandidate).where(
        VulnerabilityCandidate.actor_id == actor_id,
        VulnerabilityCandidate.id == candidate_id,
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise LookupError(f"candidate {candidate_id!r} not found for actor {actor_id!r}")
    row.status = "candidate"
    row.last_verification_error = error
    row.updated_at = _utcnow()
    await session.flush()
    return row


async def dismiss_vulnerability_candidate(
    session: AsyncSession,
    actor_id: str,
    candidate_id: int,
) -> VulnerabilityCandidate:
    """Hide a false-positive candidate from default risk views."""

    stmt = select(VulnerabilityCandidate).where(
        VulnerabilityCandidate.actor_id == actor_id,
        VulnerabilityCandidate.id == candidate_id,
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise LookupError(f"candidate {candidate_id!r} not found for actor {actor_id!r}")
    row.status = "dismissed"
    row.updated_at = _utcnow()
    await session.flush()
    return row


async def verify_vulnerability_candidate(
    session: AsyncSession,
    actor_id: str,
    candidate_id: int,
    *,
    severity: str,
    discovered_by: str,
    evidence: Optional[dict[str, Any]] = None,
    raw_log_path: Optional[str] = None,
) -> tuple[VulnerabilityCandidate, Vulnerability]:
    """Promote a candidate after explicit active verification succeeds."""

    stmt = select(VulnerabilityCandidate).where(
        VulnerabilityCandidate.actor_id == actor_id,
        VulnerabilityCandidate.id == candidate_id,
    )
    candidate = (await session.execute(stmt)).scalar_one_or_none()
    if candidate is None:
        raise LookupError(f"candidate {candidate_id!r} not found for actor {actor_id!r}")
    vuln = await upsert_vulnerability(
        session,
        actor_id,
        asset_id=candidate.asset_id,
        service_id=candidate.service_id,
        severity=severity,
        category=candidate.category,
        title=candidate.title,
        cve_id=candidate.cve_id,
        evidence=evidence or candidate.evidence,
        raw_log_path=raw_log_path,
        discovered_by=discovered_by,
    )
    candidate.status = "verified"
    candidate.last_verification_error = None
    candidate.updated_at = _utcnow()
    await session.flush()
    return candidate, vuln


# ---------------------------------------------------------------------------
# Dashboard aggregations
#
# Contract: `.trellis/spec/backend/dashboard-aggregation.md`.
# All functions are **read-only** and **actor_id scoped**. They return plain
# Python structures (dicts / lists) so the HTTP handler in
# ``secbot/channels/websocket.py`` can serialise them directly.
# ---------------------------------------------------------------------------


# SQLite stores DATETIME as ISO-8601 text; SQLAlchemy's ``func.date`` maps to
# the ``date(...)`` SQLite function, which returns ``YYYY-MM-DD`` respecting
# the second argument (``'localtime'``). The project deploys with UTC+8.
_SEVERITY_TREND_ORDER: tuple[str, ...] = ("critical", "high", "medium", "low")
_ASSET_TYPE_ORDER: tuple[str, ...] = (
    "业务",
    "智能体",
    "OA",
    "中间件",
    "支撑",
    "内网",
    "其他",
)
_VULN_CATEGORY_ORDER: tuple[str, ...] = (
    "injection",
    "auth",
    "xss",
    "misconfig",
    "exposure",
    "weak_password",
    "cve",
    "other",
)


async def _count_in_window(
    session: AsyncSession,
    stmt_builder,
    *,
    start: datetime,
    end: datetime,
    created_at_col,
) -> int:
    """Execute ``stmt_builder()`` with an extra ``created_at`` window filter."""

    stmt = stmt_builder().where(created_at_col >= start, created_at_col < end)
    return int((await session.execute(stmt)).scalar() or 0)


async def summary_counts(
    session: AsyncSession,
    actor_id: str,
    *,
    now: Optional[datetime] = None,
) -> dict[str, dict[str, int]]:
    """Return KPI counts + 24h deltas for the 5 DB-backed cards.

    The 6th card (``agents_online``) comes from the in-memory
    :class:`~secbot.agent.subagent.SubagentManager` and is composed by the
    HTTP handler, not this function.

    Delta semantics (per dashboard-aggregation.md §2.1):
    ``delta = count(created_at in [now-24h, now)) - count(created_at in
    [now-48h, now-24h))``.

    Returns a mapping with keys ``active_tasks``, ``completed_scans``,
    ``critical_vuln``, ``asset_total``, ``pending_alerts``. Each value is
    ``{"value": int, "delta": int}``.
    """

    now = now or _utcnow()
    window_start = now - timedelta(hours=24)
    prior_start = now - timedelta(hours=48)

    # Snapshot counts (no created_at filter).
    active_statuses = ("queued", "running", "awaiting_user")

    def _scan_active_count():
        return select(func.count()).select_from(Scan).where(
            Scan.actor_id == actor_id, Scan.status.in_(active_statuses)
        )

    def _scan_completed_count():
        return select(func.count()).select_from(Scan).where(
            Scan.actor_id == actor_id, Scan.status == "completed"
        )

    def _vuln_critical_count():
        return select(func.count()).select_from(Vulnerability).where(
            Vulnerability.actor_id == actor_id, Vulnerability.severity == "critical"
        )

    def _asset_total_count():
        return select(func.count()).select_from(Asset).where(Asset.actor_id == actor_id)

    def _pending_alerts_count():
        return select(func.count()).select_from(Vulnerability).where(
            Vulnerability.actor_id == actor_id,
            Vulnerability.severity.in_(("critical", "high")),
        )

    active_tasks = int((await session.execute(_scan_active_count())).scalar() or 0)
    completed_scans = int(
        (await session.execute(_scan_completed_count())).scalar() or 0
    )
    critical_vuln = int((await session.execute(_vuln_critical_count())).scalar() or 0)
    asset_total = int((await session.execute(_asset_total_count())).scalar() or 0)
    pending_alerts = int(
        (await session.execute(_pending_alerts_count())).scalar() or 0
    )

    async def _delta(builder, created_at_col) -> int:
        current = await _count_in_window(
            session, builder, start=window_start, end=now, created_at_col=created_at_col
        )
        prior = await _count_in_window(
            session,
            builder,
            start=prior_start,
            end=window_start,
            created_at_col=created_at_col,
        )
        return current - prior

    return {
        "active_tasks": {
            "value": active_tasks,
            "delta": await _delta(_scan_active_count, Scan.created_at),
        },
        "completed_scans": {
            "value": completed_scans,
            "delta": await _delta(_scan_completed_count, Scan.created_at),
        },
        "critical_vuln": {
            "value": critical_vuln,
            "delta": await _delta(_vuln_critical_count, Vulnerability.created_at),
        },
        "asset_total": {
            "value": asset_total,
            "delta": await _delta(_asset_total_count, Asset.created_at),
        },
        "pending_alerts": {
            "value": pending_alerts,
            "delta": await _delta(_pending_alerts_count, Vulnerability.created_at),
        },
    }


def _validate_trend_range(range_: str) -> int:
    """Map the ``?range=`` query parameter to a number of days. Raises
    ``ValueError`` on unknown input (the HTTP layer translates this to 400).
    """

    mapping = {"7d": 7, "30d": 30, "90d": 90}
    if range_ not in mapping:
        raise ValueError(
            f"invalid range {range_!r}; expected one of {sorted(mapping)}"
        )
    return mapping[range_]


async def vuln_trend(
    session: AsyncSession,
    actor_id: str,
    *,
    range_: str = "30d",
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Return vuln counts per day × severity for the given range.

    Severity ``info`` is excluded. The response is pre-filled so every day in
    the window is present with ``count=0`` when no vulnerabilities were
    recorded.
    """

    days = _validate_trend_range(range_)
    now = now or _utcnow()
    window_start = now - timedelta(days=days)

    # ``date(created_at, 'localtime')`` in SQLite returns a YYYY-MM-DD string
    # using the server's local TZ (UTC+8 per §1). SQLAlchemy renders
    # ``func.date(col, 'localtime')`` accordingly; on other engines (e.g.
    # PostgreSQL in tests/prod parity) we'd fall back to a CAST.
    date_expr = func.date(Vulnerability.created_at, "localtime").label("day")

    stmt = (
        select(
            Vulnerability.severity.label("severity"),
            date_expr,
            func.count().label("n"),
        )
        .where(
            Vulnerability.actor_id == actor_id,
            Vulnerability.severity.in_(_SEVERITY_TREND_ORDER),
            Vulnerability.created_at >= window_start,
        )
        .group_by(Vulnerability.severity, date_expr)
    )
    rows = (await session.execute(stmt)).all()

    # Index results by (severity, day) for dense pre-fill.
    by_key: dict[tuple[str, str], int] = {}
    for row in rows:
        by_key[(row.severity, row.day)] = int(row.n)

    # Dense date list in the caller's local TZ. Match the SQL by using the
    # same local-time date string.
    local_now = now.astimezone()
    day_list: list[str] = []
    for offset in range(days):
        d = (local_now - timedelta(days=days - 1 - offset)).date()
        day_list.append(d.isoformat())

    series: list[dict[str, Any]] = []
    for sev in _SEVERITY_TREND_ORDER:
        series.append(
            {
                "name": sev,
                "data": [
                    {"date": d, "count": by_key.get((sev, d), 0)} for d in day_list
                ],
            }
        )

    return {"range": range_, "series": series}


async def vuln_distribution(
    session: AsyncSession,
    actor_id: str,
) -> dict[str, int]:
    """Return ``{category: count}`` over all vulnerabilities for *actor_id*.

    Only returns raw counts; bucket ordering / display names / ``cve`` +
    ``weak_password`` folding are the caller's responsibility (see
    dashboard-aggregation.md §2.3).
    """

    stmt = (
        select(Vulnerability.category, func.count().label("n"))
        .where(Vulnerability.actor_id == actor_id)
        .group_by(Vulnerability.category)
    )
    rows = (await session.execute(stmt)).all()
    counts: dict[str, int] = {cat: 0 for cat in _VULN_CATEGORY_ORDER}
    for row in rows:
        # Unknown categories collapse into "other" so an out-of-vocabulary
        # insertion (shouldn't happen because upsert validates) stays
        # observable without breaking the response shape.
        key = row.category if row.category in counts else "other"
        counts[key] = counts.get(key, 0) + int(row.n)
    return counts


async def asset_type_distribution(
    session: AsyncSession,
    actor_id: str,
) -> dict[str, int]:
    """Return ``{asset_type: count}`` keyed by ``asset.tags.type``.

    NULL / unknown / missing values are folded into ``\u5176\u4ed6``.
    """

    type_expr = func.json_extract(Asset.tags, "$.type").label("kind")
    stmt = (
        select(type_expr, func.count().label("n"))
        .where(Asset.actor_id == actor_id)
        .group_by(type_expr)
    )
    rows = (await session.execute(stmt)).all()
    counts: dict[str, int] = {t: 0 for t in _ASSET_TYPE_ORDER}
    for row in rows:
        kind = row.kind if row.kind in VALID_ASSET_TYPES else "其他"
        counts[kind] = counts.get(kind, 0) + int(row.n)
    return counts


async def asset_cluster(
    session: AsyncSession,
    actor_id: str,
) -> dict[str, dict[str, int]]:
    """Return ``{system: {high, medium, low}}`` cluster counts.

    Joins ``asset`` ↔ ``vulnerability`` on ``vulnerability.asset_id`` and
    groups by ``asset.tags.system``. Assets without ``tags.system`` are grouped
    under ``其他`` so the governed asset corpus remains visible.

    Per spec §2.5, ``critical`` vulnerabilities fold into ``high`` for the
    cluster widget; ``info`` is excluded entirely.
    """

    raw_system_expr = func.json_extract(Asset.tags, "$.system")
    system_expr = func.coalesce(raw_system_expr, "其他").label("system")

    # Join asset → vulnerability. Assets with zero vulnerabilities still need
    # to appear (§2.5 rule: "Systems with zero vulnerabilities are still
    # emitted"). We fetch the roster first, then overlay counts.
    roster_stmt = (
        select(system_expr)
        .where(Asset.actor_id == actor_id)
        .group_by(system_expr)
    )
    roster = [row.system for row in (await session.execute(roster_stmt)).all()]

    # Map severity → bucket ("critical" folds into "high", others direct).
    bucket_case = case(
        (Vulnerability.severity.in_(("critical", "high")), literal_column("'high'")),
        (Vulnerability.severity == "medium", literal_column("'medium'")),
        (Vulnerability.severity == "low", literal_column("'low'")),
        else_=literal_column("NULL"),
    ).label("bucket")

    counts_stmt = (
        select(
            system_expr,
            bucket_case,
            func.count().label("n"),
        )
        .select_from(Vulnerability)
        .join(Asset, Vulnerability.asset_id == Asset.id)
        .where(
            Asset.actor_id == actor_id,
            Vulnerability.actor_id == actor_id,
            Vulnerability.severity.in_(("critical", "high", "medium", "low")),
        )
        .group_by(system_expr, bucket_case)
    )

    cluster: dict[str, dict[str, int]] = {
        system: {"high": 0, "medium": 0, "low": 0} for system in roster
    }
    for row in (await session.execute(counts_stmt)).all():
        if row.bucket is None:
            continue
        cluster.setdefault(row.system, {"high": 0, "medium": 0, "low": 0})
        cluster[row.system][row.bucket] = int(row.n)
    return cluster


_SEVERITY_RANK: dict[str, int] = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
    "info": 0,
}


def _asset_system(asset: Asset) -> str:
    tags = asset.tags if isinstance(asset.tags, dict) else {}
    value = tags.get("system")
    return str(value) if value else "其他"


def _asset_type(asset: Asset) -> str:
    tags = asset.tags if isinstance(asset.tags, dict) else {}
    value = tags.get("type")
    return str(value) if value in VALID_ASSET_TYPES else "其他"


def _vulnerability_identity_from_row(vuln: Vulnerability) -> str:
    return vulnerability_identity_key(
        cve_id=vuln.cve_id,
        category=vuln.category,
        title=vuln.title,
    )


async def asset_risk_topology(
    session: AsyncSession,
    actor_id: str,
    *,
    business_system: Optional[str] = None,
    subnet: Optional[str] = None,
    asset_type: Optional[str] = None,
    vulnerability_identity: Optional[str] = None,
    candidate_status: Optional[str] = None,
    recent_scan: Optional[str] = None,
    focus_id: Optional[str] = None,
) -> dict[str, Any]:
    """Build the Asset Risk Topology graph from current CMDB rows.

    This is a derived read model. It does not persist topology relationships or
    infer physical network links.
    """

    network: ipaddress._BaseNetwork | None = None
    if subnet:
        try:
            network = ipaddress.ip_network(subnet, strict=False)
        except ValueError as exc:
            raise ValueError(f"invalid subnet {subnet!r}") from exc
    if candidate_status is not None and candidate_status not in VALID_VULN_CANDIDATE_STATUSES:
        raise ValueError(
            "invalid candidate status "
            f"{candidate_status!r}; expected one of {sorted(VALID_VULN_CANDIDATE_STATUSES)}"
        )

    asset_rows = list(
        (await session.execute(
            select(Asset).where(Asset.actor_id == actor_id).order_by(Asset.id.asc())
        )).scalars().all()
    )

    def _asset_matches(asset: Asset) -> bool:
        if business_system and _asset_system(asset) != business_system:
            return False
        if asset_type and _asset_type(asset) != asset_type:
            return False
        if recent_scan and asset.scan_id != recent_scan:
            return False
        if network is not None:
            if not asset.ip:
                return False
            try:
                if ipaddress.ip_address(asset.ip) not in network:
                    return False
            except ValueError:
                return False
        return True

    assets = [asset for asset in asset_rows if _asset_matches(asset)]
    asset_ids = {asset.id for asset in assets}
    if not asset_ids:
        return {"nodes": [], "edges": [], "focus_id": None, "filters": {}}

    service_rows = list(
        (await session.execute(
            select(Service)
            .where(Service.actor_id == actor_id, Service.asset_id.in_(asset_ids))
            .order_by(Service.asset_id.asc(), Service.port.asc())
        )).scalars().all()
    )

    vuln_rows = list(
        (await session.execute(
            select(Vulnerability)
            .where(Vulnerability.actor_id == actor_id, Vulnerability.asset_id.in_(asset_ids))
            .order_by(Vulnerability.id.asc())
        )).scalars().all()
    )
    if vulnerability_identity:
        vuln_rows = [
            vuln for vuln in vuln_rows
            if _vulnerability_identity_from_row(vuln) == vulnerability_identity
        ]

    candidate_stmt = select(VulnerabilityCandidate).where(
        VulnerabilityCandidate.actor_id == actor_id,
        VulnerabilityCandidate.asset_id.in_(asset_ids),
    )
    if candidate_status is not None:
        candidate_stmt = candidate_stmt.where(VulnerabilityCandidate.status == candidate_status)
    else:
        candidate_stmt = candidate_stmt.where(VulnerabilityCandidate.status != "dismissed")
    candidate_rows = list(
        (await session.execute(candidate_stmt.order_by(VulnerabilityCandidate.id.asc())))
        .scalars()
        .all()
    )
    if vulnerability_identity:
        candidate_rows = [
            candidate for candidate in candidate_rows
            if candidate.identity_key == vulnerability_identity
        ]

    visible_asset_ids = {
        asset.id for asset in assets
        if not vulnerability_identity
    }
    if vulnerability_identity:
        visible_asset_ids = {v.asset_id for v in vuln_rows} | {
            c.asset_id for c in candidate_rows
        }
    visible_service_ids = {
        service.id for service in service_rows
        if service.asset_id in visible_asset_ids
    }
    visible_service_ids |= {
        row.service_id for row in vuln_rows + candidate_rows
        if row.service_id is not None
    }

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    affected_assets_by_node: dict[str, set[int]] = {}
    highest_severity_by_node: dict[str, str] = {}

    def _add_node(node: dict[str, Any]) -> None:
        node_id = str(node["id"])
        if node_id in node_ids:
            return
        node_ids.add(node_id)
        nodes.append(node)

    def _add_edge(source: str, target: str, *, kind: str) -> None:
        edges.append(
            {
                "id": f"{source}->{target}:{kind}",
                "source": source,
                "target": target,
                "kind": kind,
            }
        )

    for asset in assets:
        if asset.id not in visible_asset_ids:
            continue
        node_id = f"asset:{asset.id}"
        _add_node(
            {
                "id": node_id,
                "type": "asset",
                "label": asset.hostname or asset.ip or asset.target,
                "data": {
                    "asset_id": asset.id,
                    "ip": asset.ip,
                    "hostname": asset.hostname,
                    "target": asset.target,
                    "system": _asset_system(asset),
                    "asset_type": _asset_type(asset),
                    "scan_id": asset.scan_id,
                },
            }
        )

    for service in service_rows:
        if service.id not in visible_service_ids:
            continue
        node_id = f"service:{service.id}"
        _add_node(
            {
                "id": node_id,
                "type": "service",
                "label": f"{service.protocol}/{service.port}",
                "data": {
                    "service_id": service.id,
                    "asset_id": service.asset_id,
                    "port": service.port,
                    "protocol": service.protocol,
                    "service": service.service,
                    "product": service.product,
                    "version": service.version,
                    "state": service.state,
                },
            }
        )
        asset_node = f"asset:{service.asset_id}"
        if asset_node in node_ids:
            _add_edge(asset_node, node_id, kind="asset-service")

    for vuln in vuln_rows:
        identity = _vulnerability_identity_from_row(vuln)
        node_id = f"vulnerability:{identity}:confirmed"
        affected_assets_by_node.setdefault(node_id, set()).add(vuln.asset_id)
        existing_sev = highest_severity_by_node.get(node_id, "info")
        if _SEVERITY_RANK[vuln.severity] > _SEVERITY_RANK[existing_sev]:
            highest_severity_by_node[node_id] = vuln.severity
        _add_node(
            {
                "id": node_id,
                "type": "vulnerability",
                "label": vuln.cve_id or vuln.title,
                "data": {
                    "identity_key": identity,
                    "status": "confirmed",
                    "category": vuln.category,
                    "title": vuln.title,
                    "cve_id": vuln.cve_id,
                    "severity": vuln.severity,
                },
            }
        )
        source = f"service:{vuln.service_id}" if vuln.service_id else f"asset:{vuln.asset_id}"
        if source in node_ids:
            _add_edge(source, node_id, kind="confirmed-vulnerability")

    for candidate in candidate_rows:
        node_id = f"vulnerability:{candidate.identity_key}:candidate"
        affected_assets_by_node.setdefault(node_id, set()).add(candidate.asset_id)
        _add_node(
            {
                "id": node_id,
                "type": "vulnerability",
                "label": candidate.cve_id or candidate.cnvd_id or candidate.title,
                "data": {
                    "identity_key": candidate.identity_key,
                    "status": candidate.status,
                    "category": candidate.category,
                    "title": candidate.title,
                    "cve_id": candidate.cve_id,
                    "cnvd_id": candidate.cnvd_id,
                    "source": candidate.source,
                    "last_verification_error": candidate.last_verification_error,
                },
            }
        )
        source = (
            f"service:{candidate.service_id}"
            if candidate.service_id
            else f"asset:{candidate.asset_id}"
        )
        if source in node_ids:
            _add_edge(source, node_id, kind="candidate-vulnerability")

    for node in nodes:
        if node["type"] != "vulnerability":
            continue
        affected = affected_assets_by_node.get(str(node["id"]), set())
        node["data"]["affected_asset_count"] = len(affected)
        if node["data"].get("status") == "confirmed":
            node["data"]["severity"] = highest_severity_by_node.get(str(node["id"]), "info")
        node["data"]["radius"] = 18 + min(len(affected), 12) * 3

    return {
        "nodes": nodes,
        "edges": edges,
        "focus_id": focus_id if focus_id in node_ids else None,
        "filters": {
            "business_system": business_system,
            "subnet": subnet,
            "asset_type": asset_type,
            "vulnerability_identity": vulnerability_identity,
            "candidate_status": candidate_status,
            "recent_scan": recent_scan,
        },
    }


# ---------------------------------------------------------------------------
# Report metadata (report_meta)
#
# Contract: `.trellis/spec/backend/report-meta.md` + `cmdb-schema.md` §2.5.
# One row per successful report render. All reads are ``actor_id`` scoped.
# ---------------------------------------------------------------------------


_REPORT_RANGE_DAYS: dict[str, Optional[int]] = {
    "7d": 7,
    "30d": 30,
    "all": None,
}


def _format_report_id(created_at: datetime, seq: int) -> str:
    """Format the public ``RPT-YYYY-MMDD-<seq>`` id.

    Uses *local* time because operators read the id and expect the date to
    match their wall-clock (same rationale as ``func.date(..., 'localtime')``
    in the dashboard aggregations).
    """

    local = created_at.astimezone()
    return f"RPT-{local.year:04d}-{local.month:02d}{local.day:02d}-{seq:03d}"


async def _next_report_seq(
    session: AsyncSession, actor_id: str, created_at: datetime
) -> int:
    """Return the 1-based sequence of the next report for this local date.

    Per report-meta.md §3.2: ``seq = COUNT(*) WHERE DATE(created_at)=today``
    (plus one). The formula is deliberately **not** partitioned by
    ``actor_id`` — the display id is a public, globally-unique handle for
    URL routing; v1 runs single-user so this keeps seq stable and avoids PK
    collisions when multi-tenant lands.
    """

    del actor_id  # kept in signature for future per-actor display scoping
    local_date = created_at.astimezone().date().isoformat()
    date_expr = func.date(ReportMeta.created_at, "localtime")
    stmt = (
        select(func.count()).select_from(ReportMeta).where(date_expr == local_date)
    )
    current = int((await session.execute(stmt)).scalar() or 0)
    return current + 1


async def insert_report_meta(
    session: AsyncSession,
    actor_id: str,
    *,
    scan_id: str,
    title: str,
    type: str,
    author: str,
    status: str = "published",
    critical_count: int = 0,
    download_path: Optional[str] = None,
    created_at: Optional[datetime] = None,
) -> ReportMeta:
    """Insert a ``report_meta`` row and return the persisted ORM object.

    Validates ``type`` / ``status`` against the spec vocabularies. ``id`` is
    auto-generated as ``RPT-YYYY-MMDD-<seq>`` where ``seq`` restarts per day
    per actor.
    """

    if type not in VALID_REPORT_TYPES:
        raise ValueError(
            f"invalid report type {type!r}; expected one of {sorted(VALID_REPORT_TYPES)}"
        )
    if status not in VALID_REPORT_STATUSES:
        raise ValueError(
            f"invalid report status {status!r}; expected one of {sorted(VALID_REPORT_STATUSES)}"
        )
    if critical_count < 0:
        raise ValueError("critical_count must be >= 0")

    when = created_at or _utcnow()
    seq = await _next_report_seq(session, actor_id, when)
    rid = _format_report_id(when, seq)

    row = ReportMeta(
        id=rid,
        scan_id=scan_id,
        title=title,
        type=type,
        status=status,
        critical_count=int(critical_count),
        author=author,
        download_path=download_path,
        actor_id=actor_id or DEFAULT_ACTOR,
        created_at=when,
    )
    session.add(row)
    await session.flush()
    return row


async def list_reports(
    session: AsyncSession,
    actor_id: str,
    *,
    range_: str = "30d",
    type: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    now: Optional[datetime] = None,
) -> tuple[list[ReportMeta], int]:
    """Return ``(rows, total)`` for the ``/api/reports`` listing.

    ``range_`` accepts ``'7d' | '30d' | 'all'``; unknown values raise
    ``ValueError`` (HTTP layer maps to 400).
    """

    if range_ not in _REPORT_RANGE_DAYS:
        raise ValueError(
            f"invalid range {range_!r}; expected one of {sorted(_REPORT_RANGE_DAYS)}"
        )
    if type is not None and type not in VALID_REPORT_TYPES:
        raise ValueError(
            f"invalid report type {type!r}; expected one of {sorted(VALID_REPORT_TYPES)}"
        )
    if status is not None and status not in VALID_REPORT_STATUSES:
        raise ValueError(
            f"invalid report status {status!r}; expected one of {sorted(VALID_REPORT_STATUSES)}"
        )
    if limit < 0 or offset < 0:
        raise ValueError("limit / offset must be non-negative")

    base = select(ReportMeta).where(ReportMeta.actor_id == actor_id)
    count_base = select(func.count()).select_from(ReportMeta).where(
        ReportMeta.actor_id == actor_id
    )

    days = _REPORT_RANGE_DAYS[range_]
    if days is not None:
        now = now or _utcnow()
        window_start = now - timedelta(days=days)
        base = base.where(ReportMeta.created_at >= window_start)
        count_base = count_base.where(ReportMeta.created_at >= window_start)
    if type is not None:
        base = base.where(ReportMeta.type == type)
        count_base = count_base.where(ReportMeta.type == type)
    if status is not None:
        base = base.where(ReportMeta.status == status)
        count_base = count_base.where(ReportMeta.status == status)

    total = int((await session.execute(count_base)).scalar() or 0)
    stmt = (
        base.order_by(ReportMeta.created_at.desc(), ReportMeta.id.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    return rows, total


async def get_report(
    session: AsyncSession, actor_id: str, report_id: str
) -> Optional[ReportMeta]:
    stmt = select(ReportMeta).where(
        ReportMeta.actor_id == actor_id, ReportMeta.id == report_id
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def update_report_status(
    session: AsyncSession,
    actor_id: str,
    report_id: str,
    *,
    new_status: str,
) -> ReportMeta:
    """Transition a report to ``new_status``.

    Enforces the state machine from report-meta.md §3.3. Raises
    ``LookupError`` if the row does not exist for *actor_id*; ``ValueError``
    when the transition is illegal.
    """

    if new_status not in VALID_REPORT_STATUSES:
        raise ValueError(
            f"invalid report status {new_status!r}; expected one of "
            f"{sorted(VALID_REPORT_STATUSES)}"
        )
    row = await get_report(session, actor_id, report_id)
    if row is None:
        raise LookupError(
            f"report {report_id!r} not found for actor {actor_id!r}"
        )
    if row.status == new_status:
        return row
    allowed = REPORT_STATUS_TRANSITIONS.get(row.status, frozenset())
    if new_status not in allowed:
        raise ValueError(
            f"illegal report status transition: {row.status!r} -> {new_status!r}"
        )
    row.status = new_status
    await session.flush()
    return row


__all__ = [
    # Scan
    "create_scan",
    "get_scan",
    "list_scans",
    "update_scan_status",
    # Asset / Service / Vulnerability
    "upsert_asset",
    "list_assets",
    "upsert_service",
    "list_services",
    "upsert_vulnerability",
    "list_vulnerabilities",
    # Dashboard aggregations
    "summary_counts",
    "vuln_trend",
    "vuln_distribution",
    "asset_type_distribution",
    "asset_cluster",
    # Report meta
    "insert_report_meta",
    "list_reports",
    "get_report",
    "update_report_status",
    # Misc
    "new_ulid",
]

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

import secrets
import time
from datetime import datetime, timezone
from typing import Any, Iterable, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from secbot.cmdb.models import (
    DEFAULT_ACTOR,
    VALID_SCAN_STATUSES,
    VALID_SEVERITIES,
    VALID_VULN_CATEGORIES,
    Asset,
    Scan,
    Service,
    Vulnerability,
)

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
    tags: Optional[list[str]] = None,
) -> Asset:
    """Insert-or-update an asset keyed on ``(actor_id, scan_id, target)``.

    Within a single scan we treat ``target`` as the natural key (a re-scan
    that revises ``ip``/``hostname`` MUST update the existing row, not insert
    a duplicate).
    """

    stmt = select(Asset).where(
        Asset.actor_id == actor_id,
        Asset.scan_id == scan_id,
        Asset.target == target,
    )
    asset = (await session.execute(stmt)).scalar_one_or_none()

    if asset is None:
        asset = Asset(
            actor_id=actor_id or DEFAULT_ACTOR,
            scan_id=scan_id,
            target=target,
            ip=ip,
            hostname=hostname,
            os_guess=os_guess,
            tags=list(tags) if tags else None,
        )
        session.add(asset)
    else:
        if ip is not None:
            asset.ip = ip
        if hostname is not None:
            asset.hostname = hostname
        if os_guess is not None:
            asset.os_guess = os_guess
        if tags is not None:
            asset.tags = list(tags)
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
        vuln.severity = severity
        vuln.category = category
        vuln.discovered_by = discovered_by
        if evidence is not None:
            vuln.evidence = evidence
        if raw_log_path is not None:
            vuln.raw_log_path = raw_log_path

    await session.flush()
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

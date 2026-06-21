"""High-level repository helpers for the Threat Intel database.

All write operations use upsert semantics — duplicate Feed pulls must not
create semantic duplicates.  The repo is the **only** layer that touches
the session directly; API handlers and feed pullers call these helpers.

Design follows :mod:`secbot.cmdb.repo` patterns: ULID primary keys,
``actor_id`` multi-tenant reservation, and structured ``source_refs``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import String, and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from secbot.threat_intel.models import (
    DEFAULT_ACTOR,
    AptAlias,
    FeedPullRun,
    MaritimeEvent,
    ThreatGroup,
    ThreatGroupVulnAssoc,
    ThreatInfraIP,
    ThreatMalwareFamily,
    ThreatVuln,
    Watchlist,
)

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ULID (Crockford base32, 26 chars) — standalone implementation
# ---------------------------------------------------------------------------

_ULID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_ULID_TIME_LEN = 10


def _encode_ulid(timestamp_ms: int, random_bytes: bytes) -> str:
    """Encode a ULID from a millisecond timestamp and 10 random bytes."""
    # 48-bit timestamp (10 chars) + 80-bit random (16 chars) = 26 chars
    ts = timestamp_ms
    ts_chars = [""] * _ULID_TIME_LEN
    for i in range(_ULID_TIME_LEN - 1, -1, -1):
        ts_chars[i] = _ULID_ALPHABET[ts & 0x1F]
        ts >>= 5

    rand_int = int.from_bytes(random_bytes, "big")
    rand_chars = [""] * 16
    for i in range(15, -1, -1):
        rand_chars[i] = _ULID_ALPHABET[rand_int & 0x1F]
        rand_int >>= 5

    return "".join(ts_chars) + "".join(rand_chars)


def generate_ulid() -> str:
    """Generate a new ULID string (26 chars, Crockford base32)."""
    import os
    import time
    ts = int(time.time() * 1000)
    return _encode_ulid(ts, os.urandom(10))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Pagination helper
# ---------------------------------------------------------------------------

def _paginate(page: int, page_size: int) -> tuple[int, int]:
    """Clamp page/page_size and return (limit, offset)."""
    page = max(1, page)
    page_size = max(1, min(100, page_size))
    return page_size, (page - 1) * page_size


# ---------------------------------------------------------------------------
# Threat Group
# ---------------------------------------------------------------------------

async def upsert_threat_group(
    session: AsyncSession,
    *,
    name: str,
    mitre_id: Optional[str] = None,
    aliases: Optional[list] = None,
    description: Optional[str] = None,
    origin_country: Optional[str] = None,
    target_sectors: Optional[list] = None,
    techniques: Optional[list] = None,
    first_seen: Optional[Any] = None,
    last_seen: Optional[Any] = None,
    source: str = "mitre",
    confidence: float = 1.0,
    source_refs: Optional[list] = None,
) -> tuple[ThreatGroup, bool]:
    """Upsert a Threat Group by ``mitre_id`` (if set) or lower(name).

    Returns ``(group, created)`` where ``created`` is True if a new row
    was inserted.
    """
    # Try by mitre_id first, then by name
    existing: Optional[ThreatGroup] = None
    if mitre_id:
        result = await session.execute(
            select(ThreatGroup).where(ThreatGroup.mitre_id == mitre_id)
        )
        existing = result.scalar_one_or_none()

    if existing is None:
        result = await session.execute(
            select(ThreatGroup).where(func.lower(ThreatGroup.name) == name.lower())
        )
        existing = result.scalar_one_or_none()

    if existing is not None:
        # Update fields
        if aliases is not None:
            existing.aliases = aliases
        if description is not None:
            existing.description = description
        if origin_country is not None:
            existing.origin_country = origin_country
        if target_sectors is not None:
            existing.target_sectors = target_sectors
        if techniques is not None:
            existing.techniques = techniques
        if mitre_id and not existing.mitre_id:
            existing.mitre_id = mitre_id
        if first_seen is not None:
            existing.first_seen = first_seen
        if last_seen is not None:
            existing.last_seen = last_seen
        if source_refs is not None:
            existing.source_refs = source_refs
        existing.confidence = max(existing.confidence, confidence)
        existing.last_ingested_at = _utcnow()
        return existing, False

    group = ThreatGroup(
        id=generate_ulid(),
        name=name,
        mitre_id=mitre_id,
        aliases=aliases,
        description=description,
        origin_country=origin_country,
        target_sectors=target_sectors,
        techniques=techniques,
        first_seen=first_seen,
        last_seen=last_seen,
        source=source,
        confidence=confidence,
        source_refs=source_refs,
    )
    session.add(group)
    await session.flush()
    return group, True


async def list_threat_groups(
    session: AsyncSession,
    *,
    q: Optional[str] = None,
    watched_only: bool = False,
    actor_id: str = DEFAULT_ACTOR,
    origin_country: Optional[str] = None,
    target_sector: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """List threat groups with pagination, search, and filters.

    Search covers name, aliases JSON, and apt_alias table.
    Returns ``{items, page, page_size, total}``.
    """
    limit, offset = _paginate(page, page_size)

    stmt = select(ThreatGroup)

    # Watchlist filter via EXISTS subquery
    if watched_only:
        watchlist_exists = (
            select(Watchlist.id)
            .where(
                and_(
                    Watchlist.group_id == ThreatGroup.id,
                    Watchlist.actor_id == actor_id,
                )
            )
            .exists()
        )
        stmt = stmt.where(watchlist_exists)

    if origin_country:
        stmt = stmt.where(ThreatGroup.origin_country == origin_country)

    if target_sector:
        # target_sectors is a JSON array — use LIKE for SQLite compatibility
        stmt = stmt.where(
            func.lower(ThreatGroup.target_sectors.cast(String)).like(f'%"{target_sector.lower()}"%')
        )

    # Search: name OR aliases OR apt_alias
    if q:
        q_lower = q.lower()
        # Name search (case-insensitive)
        name_cond = func.lower(ThreatGroup.name).like(f"%{q_lower}%")
        # Alias search in apt_alias table
        alias_subq = (
            select(AptAlias.group_id)
            .where(func.lower(AptAlias.alias_name).like(f"%{q_lower}%"))
            .scalar_subquery()
        )
        stmt = stmt.where(
            or_(
                name_cond,
                ThreatGroup.id.in_(alias_subq),
            )
        )

    # Count total
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await session.execute(count_stmt)
    total = total_result.scalar() or 0

    # Default sort: is_watched DESC, name ASC
    # For is_watched, we need a left join to watchlist
    watchlist_flag = (
        select(Watchlist.group_id)
        .where(
            and_(
                Watchlist.group_id == ThreatGroup.id,
                Watchlist.actor_id == actor_id,
            )
        )
        .exists()
        .label("is_watched")
    )
    stmt = stmt.add_columns(watchlist_flag)
    stmt = stmt.order_by(
        watchlist_flag.desc(),
        ThreatGroup.name.asc(),
    )
    stmt = stmt.limit(limit).offset(offset)

    result = await session.execute(stmt)
    rows = result.all()

    items = []
    for row in rows:
        group = row[0]
        items.append({
            "id": group.id,
            "name": group.name,
            "aliases": group.aliases or [],
            "description": group.description,
            "origin_country": group.origin_country,
            "target_sectors": group.target_sectors or [],
            "mitre_id": group.mitre_id,
            "first_seen": group.first_seen.isoformat() if group.first_seen else None,
            "last_seen": group.last_seen.isoformat() if group.last_seen else None,
            "source": group.source,
            "confidence": group.confidence,
            "is_watched": row[1],  # watchlist_flag
        })

    return {"items": items, "page": page, "page_size": page_size, "total": total}


async def get_threat_group(
    session: AsyncSession,
    group_id: str,
    *,
    actor_id: str = DEFAULT_ACTOR,
) -> Optional[dict[str, Any]]:
    """Get a single threat group with all relations and is_watched flag."""
    result = await session.execute(
        select(ThreatGroup).where(ThreatGroup.id == group_id)
    )
    group = result.scalar_one_or_none()
    if group is None:
        return None

    # Check watchlist
    wl_result = await session.execute(
        select(Watchlist).where(
            and_(Watchlist.group_id == group_id, Watchlist.actor_id == actor_id)
        )
    )
    is_watched = wl_result.scalar_one_or_none() is not None

    # Related IPs
    ips_result = await session.execute(
        select(ThreatInfraIP).where(ThreatInfraIP.group_id == group_id)
    )
    ips = ips_result.scalars().all()

    # Related malware
    malware_result = await session.execute(
        select(ThreatMalwareFamily).where(ThreatMalwareFamily.group_id == group_id)
    )
    malware = malware_result.scalars().all()

    # Related vulns (exploited only by default)
    vulns_result = await session.execute(
        select(ThreatGroupVulnAssoc, ThreatVuln)
        .join(ThreatVuln, ThreatGroupVulnAssoc.vulnerability_id == ThreatVuln.id)
        .where(ThreatGroupVulnAssoc.group_id == group_id)
    )
    vuln_rows = vulns_result.all()

    # APT aliases
    alias_result = await session.execute(
        select(AptAlias).where(AptAlias.group_id == group_id)
    )
    aliases = alias_result.scalars().all()

    return {
        "id": group.id,
        "name": group.name,
        "aliases": group.aliases or [],
        "description": group.description,
        "origin_country": group.origin_country,
        "target_sectors": group.target_sectors or [],
        "mitre_id": group.mitre_id,
        "techniques": group.techniques or [],
        "first_seen": group.first_seen.isoformat() if group.first_seen else None,
        "last_seen": group.last_seen.isoformat() if group.last_seen else None,
        "source": group.source,
        "confidence": group.confidence,
        "source_refs": group.source_refs or [],
        "is_watched": is_watched,
        "infra_ips": [
            {
                "id": ip.id,
                "ip_address": ip.ip_address,
                "ip_type": ip.ip_type,
                "malware_family": ip.malware_family,
                "geo_country": ip.geo_country,
                "asn": ip.asn,
                "first_seen": ip.first_seen.isoformat() if ip.first_seen else None,
                "last_seen": ip.last_seen.isoformat() if ip.last_seen else None,
                "status": ip.status,
                "source": ip.source,
                "confidence": ip.confidence,
            }
            for ip in ips
        ],
        "malware_families": [
            {
                "id": m.id,
                "family_name": m.family_name,
                "aliases": m.aliases or [],
                "type": m.type,
                "platform": m.platform or [],
                "first_seen": m.first_seen.isoformat() if m.first_seen else None,
                "last_active": m.last_active.isoformat() if m.last_active else None,
                "source": m.source,
            }
            for m in malware
        ],
        "vulnerabilities": [
            {
                "id": assoc.vulnerability_id,
                "cve_id": vuln.cve_id,
                "title": vuln.title,
                "cvss_score": vuln.cvss_score,
                "severity": vuln.severity,
                "is_cisa_kev": vuln.is_cisa_kev,
                "relationship_type": assoc.relationship_type,
                "confidence": assoc.confidence,
                "last_seen": assoc.last_seen.isoformat() if assoc.last_seen else None,
            }
            for assoc, vuln in vuln_rows
        ],
        "apt_aliases": [
            {
                "alias_name": a.alias_name,
                "naming_org": a.naming_org,
                "confidence": a.confidence,
            }
            for a in aliases
        ],
    }


# ---------------------------------------------------------------------------
# Threat Infrastructure IP
# ---------------------------------------------------------------------------

async def upsert_threat_infra_ip(
    session: AsyncSession,
    *,
    group_id: str,
    ip_address: str,
    ip_type: str = "c2",
    malware_family: Optional[str] = None,
    geo_country: Optional[str] = None,
    asn: Optional[str] = None,
    first_seen: Optional[datetime] = None,
    last_seen: Optional[datetime] = None,
    status: str = "active",
    source: str = "threatfox",
    confidence: float = 0.7,
    source_refs: Optional[list] = None,
    tags: Optional[list] = None,
) -> tuple[ThreatInfraIP, bool]:
    """Upsert by (group_id, ip_address, ip_type)."""
    result = await session.execute(
        select(ThreatInfraIP).where(
            and_(
                ThreatInfraIP.group_id == group_id,
                ThreatInfraIP.ip_address == ip_address,
                ThreatInfraIP.ip_type == ip_type,
            )
        )
    )
    existing = result.scalar_one_or_none()

    if existing is not None:
        if malware_family is not None:
            existing.malware_family = malware_family
        if geo_country is not None:
            existing.geo_country = geo_country
        if asn is not None:
            existing.asn = asn
        if first_seen is not None and (
            existing.first_seen is None or first_seen < existing.first_seen
        ):
            existing.first_seen = first_seen
        if last_seen is not None and (
            existing.last_seen is None or last_seen > existing.last_seen
        ):
            existing.last_seen = last_seen
        existing.status = status
        existing.confidence = max(existing.confidence, confidence)
        if source_refs is not None:
            existing.source_refs = source_refs
        existing.last_ingested_at = _utcnow()
        return existing, False

    ip = ThreatInfraIP(
        id=generate_ulid(),
        group_id=group_id,
        ip_address=ip_address,
        ip_type=ip_type,
        malware_family=malware_family,
        geo_country=geo_country,
        asn=asn,
        first_seen=first_seen,
        last_seen=last_seen,
        status=status,
        source=source,
        confidence=confidence,
        source_refs=source_refs,
        tags=tags,
    )
    session.add(ip)
    await session.flush()
    return ip, True


async def list_threat_infra_ips(
    session: AsyncSession,
    *,
    group_id: Optional[str] = None,
    ip_type: Optional[str] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """List threat infrastructure IPs with pagination and filters."""
    limit, offset = _paginate(page, page_size)
    stmt = select(ThreatInfraIP)

    if group_id:
        stmt = stmt.where(ThreatInfraIP.group_id == group_id)
    if ip_type:
        stmt = stmt.where(ThreatInfraIP.ip_type == ip_type)
    if status:
        stmt = stmt.where(ThreatInfraIP.status == status)
    if q:
        stmt = stmt.where(ThreatInfraIP.ip_address.like(f"%{q}%"))

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await session.execute(count_stmt)).scalar() or 0

    stmt = stmt.order_by(ThreatInfraIP.last_seen.desc()).limit(limit).offset(offset)
    result = await session.execute(stmt)
    rows = result.scalars().all()

    items = [
        {
            "id": ip.id,
            "group_id": ip.group_id,
            "ip_address": ip.ip_address,
            "ip_type": ip.ip_type,
            "malware_family": ip.malware_family,
            "geo_country": ip.geo_country,
            "asn": ip.asn,
            "first_seen": ip.first_seen.isoformat() if ip.first_seen else None,
            "last_seen": ip.last_seen.isoformat() if ip.last_seen else None,
            "status": ip.status,
            "source": ip.source,
            "confidence": ip.confidence,
        }
        for ip in rows
    ]
    return {"items": items, "page": page, "page_size": page_size, "total": total}


# ---------------------------------------------------------------------------
# Threat Vulnerability
# ---------------------------------------------------------------------------

async def upsert_threat_vuln(
    session: AsyncSession,
    *,
    cve_id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    cvss_score: Optional[float] = None,
    severity: str = "high",
    affected_products: Optional[list] = None,
    is_supply_chain: bool = False,
    has_poc: bool = False,
    exploit_available: bool = False,
    is_cisa_kev: bool = False,
    cisa_kev_date: Optional[Any] = None,
    published_date: Optional[Any] = None,
    primary_source: str = "cisa_kev",
    sources: Optional[list] = None,
    source_refs: Optional[list] = None,
    tags: Optional[list] = None,
) -> tuple[ThreatVuln, bool]:
    """Upsert by cve_id."""
    result = await session.execute(
        select(ThreatVuln).where(ThreatVuln.cve_id == cve_id)
    )
    existing = result.scalar_one_or_none()

    if existing is not None:
        if title is not None:
            existing.title = title
        if description is not None:
            existing.description = description
        if cvss_score is not None:
            existing.cvss_score = cvss_score
        # CISA KEV severity: max(CVSS mapping, high)
        if is_cisa_kev and not existing.is_cisa_kev:
            existing.is_cisa_kev = True
            existing.severity = "critical" if (
                cvss_score is not None and cvss_score >= 9.0
            ) else "high"
        if cisa_kev_date is not None:
            existing.cisa_kev_date = cisa_kev_date
        if affected_products is not None:
            existing.affected_products = affected_products
        if is_supply_chain:
            existing.is_supply_chain = True
        if has_poc:
            existing.has_poc = True
        if exploit_available:
            existing.exploit_available = True
        if sources is not None:
            existing.sources = sources
        if source_refs is not None:
            existing.source_refs = source_refs
        if tags is not None:
            existing.tags = tags
        existing.last_ingested_at = _utcnow()
        return existing, False

    # Determine severity for new records
    if is_cisa_kev:
        severity = "critical" if (cvss_score is not None and cvss_score >= 9.0) else "high"
    elif cvss_score is not None:
        severity = "critical" if cvss_score >= 9.0 else "high"

    vuln = ThreatVuln(
        id=generate_ulid(),
        cve_id=cve_id,
        title=title,
        description=description,
        cvss_score=cvss_score,
        severity=severity,
        affected_products=affected_products,
        is_supply_chain=is_supply_chain,
        has_poc=has_poc,
        exploit_available=exploit_available,
        is_cisa_kev=is_cisa_kev,
        cisa_kev_date=cisa_kev_date,
        published_date=published_date,
        primary_source=primary_source,
        sources=sources,
        source_refs=source_refs,
        tags=tags,
    )
    session.add(vuln)
    await session.flush()
    return vuln, True


async def list_threat_vulns(
    session: AsyncSession,
    *,
    q: Optional[str] = None,
    severity: Optional[str] = None,
    is_supply_chain: Optional[bool] = None,
    is_cisa_kev: Optional[bool] = None,
    has_poc: Optional[bool] = None,
    exploit_available: Optional[bool] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """List threat vulnerabilities with pagination and filters."""
    limit, offset = _paginate(page, page_size)
    stmt = select(ThreatVuln)

    if q:
        q_lower = q.lower()
        stmt = stmt.where(
            or_(
                func.lower(ThreatVuln.cve_id).like(f"%{q_lower}%"),
                func.lower(ThreatVuln.title).like(f"%{q_lower}%"),
            )
        )
    if severity:
        stmt = stmt.where(ThreatVuln.severity == severity)
    if is_supply_chain is not None:
        stmt = stmt.where(ThreatVuln.is_supply_chain == is_supply_chain)
    if is_cisa_kev is not None:
        stmt = stmt.where(ThreatVuln.is_cisa_kev == is_cisa_kev)
    if has_poc is not None:
        stmt = stmt.where(ThreatVuln.has_poc == has_poc)
    if exploit_available is not None:
        stmt = stmt.where(ThreatVuln.exploit_available == exploit_available)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await session.execute(count_stmt)).scalar() or 0

    stmt = stmt.order_by(ThreatVuln.last_ingested_at.desc()).limit(limit).offset(offset)
    result = await session.execute(stmt)
    rows = result.scalars().all()

    items = [
        {
            "id": v.id,
            "cve_id": v.cve_id,
            "title": v.title,
            "cvss_score": v.cvss_score,
            "severity": v.severity,
            "is_supply_chain": v.is_supply_chain,
            "is_cisa_kev": v.is_cisa_kev,
            "has_poc": v.has_poc,
            "exploit_available": v.exploit_available,
            "published_date": v.published_date.isoformat() if v.published_date else None,
            "cisa_kev_date": v.cisa_kev_date.isoformat() if v.cisa_kev_date else None,
            "primary_source": v.primary_source,
        }
        for v in rows
    ]
    return {"items": items, "page": page, "page_size": page_size, "total": total}


# ---------------------------------------------------------------------------
# Threat Malware Family
# ---------------------------------------------------------------------------

async def upsert_threat_malware_family(
    session: AsyncSession,
    *,
    group_id: str,
    family_name: str,
    aliases: Optional[list] = None,
    description: Optional[str] = None,
    type: str = "other",
    platform: Optional[list] = None,
    sample_hashes: Optional[list] = None,
    yara_rules: Optional[list] = None,
    first_seen: Optional[Any] = None,
    last_active: Optional[Any] = None,
    source: str = "manual",
    confidence: float = 0.8,
    source_refs: Optional[list] = None,
    tags: Optional[list] = None,
) -> tuple[ThreatMalwareFamily, bool]:
    """Upsert by (group_id, lower(family_name))."""
    result = await session.execute(
        select(ThreatMalwareFamily).where(
            and_(
                ThreatMalwareFamily.group_id == group_id,
                func.lower(ThreatMalwareFamily.family_name) == family_name.lower(),
            )
        )
    )
    existing = result.scalar_one_or_none()

    if existing is not None:
        if aliases is not None:
            existing.aliases = aliases
        if description is not None:
            existing.description = description
        if sample_hashes is not None:
            existing.sample_hashes = sample_hashes
        if yara_rules is not None:
            existing.yara_rules = yara_rules
        if first_seen is not None and (
            existing.first_seen is None or first_seen < existing.first_seen
        ):
            existing.first_seen = first_seen
        if last_active is not None and (
            existing.last_active is None or last_active > existing.last_active
        ):
            existing.last_active = last_active
        existing.confidence = max(existing.confidence, confidence)
        existing.last_ingested_at = _utcnow()
        return existing, False

    family = ThreatMalwareFamily(
        id=generate_ulid(),
        group_id=group_id,
        family_name=family_name,
        aliases=aliases,
        description=description,
        type=type,
        platform=platform,
        sample_hashes=sample_hashes,
        yara_rules=yara_rules,
        first_seen=first_seen,
        last_active=last_active,
        source=source,
        confidence=confidence,
        source_refs=source_refs,
        tags=tags,
    )
    session.add(family)
    await session.flush()
    return family, True


async def list_threat_malware(
    session: AsyncSession,
    *,
    group_id: Optional[str] = None,
    type: Optional[str] = None,
    platform: Optional[str] = None,
    q: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """List malware families with pagination and filters."""
    limit, offset = _paginate(page, page_size)
    stmt = select(ThreatMalwareFamily)

    if group_id:
        stmt = stmt.where(ThreatMalwareFamily.group_id == group_id)
    if type:
        stmt = stmt.where(ThreatMalwareFamily.type == type)
    if q:
        stmt = stmt.where(func.lower(ThreatMalwareFamily.family_name).like(f"%{q.lower()}%"))

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await session.execute(count_stmt)).scalar() or 0

    stmt = stmt.order_by(ThreatMalwareFamily.last_active.desc()).limit(limit).offset(offset)
    result = await session.execute(stmt)
    rows = result.scalars().all()

    items = [
        {
            "id": m.id,
            "group_id": m.group_id,
            "family_name": m.family_name,
            "aliases": m.aliases or [],
            "type": m.type,
            "platform": m.platform or [],
            "first_seen": m.first_seen.isoformat() if m.first_seen else None,
            "last_active": m.last_active.isoformat() if m.last_active else None,
            "source": m.source,
        }
        for m in rows
    ]
    return {"items": items, "page": page, "page_size": page_size, "total": total}


# ---------------------------------------------------------------------------
# Maritime Event
# ---------------------------------------------------------------------------

async def upsert_maritime_event(
    session: AsyncSession,
    *,
    event_type: str,
    title: str,
    description: Optional[str] = None,
    location: Optional[dict] = None,
    severity: str = "medium",
    event_date: datetime,
    source: str = "other",
    source_url: Optional[str] = None,
    extraction_confidence: float = 1.0,
    verification_status: str = "unreviewed",
    source_refs: Optional[list] = None,
    tags: Optional[list] = None,
) -> tuple[MaritimeEvent, bool]:
    """Upsert by (source, source_url, event_date) or fingerprint."""
    if source_url:
        result = await session.execute(
            select(MaritimeEvent).where(
                and_(
                    MaritimeEvent.source == source,
                    MaritimeEvent.source_url == source_url,
                    MaritimeEvent.event_date == event_date,
                )
            )
        )
        existing = result.scalar_one_or_none()
    else:
        # Fingerprint: source + title + event_date + location.region
        result = await session.execute(
            select(MaritimeEvent).where(
                and_(
                    MaritimeEvent.source == source,
                    MaritimeEvent.title == title,
                    MaritimeEvent.event_date == event_date,
                )
            )
        )
        existing = result.scalar_one_or_none()

    if existing is not None:
        if description is not None:
            existing.description = description
        if location is not None:
            existing.location = location
        existing.severity = severity
        existing.extraction_confidence = max(existing.extraction_confidence, extraction_confidence)
        if source_refs is not None:
            existing.source_refs = source_refs
        return existing, False

    event = MaritimeEvent(
        id=generate_ulid(),
        event_type=event_type,
        title=title,
        description=description,
        location=location,
        severity=severity,
        event_date=event_date,
        source=source,
        source_url=source_url,
        extraction_confidence=extraction_confidence,
        verification_status=verification_status,
        source_refs=source_refs,
        tags=tags,
    )
    session.add(event)
    await session.flush()
    return event, True


async def list_maritime_events(
    session: AsyncSession,
    *,
    event_type: Optional[str] = None,
    severity: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    verification_status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """List maritime events with pagination and filters."""
    limit, offset = _paginate(page, page_size)
    stmt = select(MaritimeEvent)

    if event_type:
        stmt = stmt.where(MaritimeEvent.event_type == event_type)
    if severity:
        stmt = stmt.where(MaritimeEvent.severity == severity)
    if from_date:
        stmt = stmt.where(MaritimeEvent.event_date >= from_date)
    if to_date:
        stmt = stmt.where(MaritimeEvent.event_date <= to_date)
    if verification_status:
        stmt = stmt.where(MaritimeEvent.verification_status == verification_status)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await session.execute(count_stmt)).scalar() or 0

    stmt = stmt.order_by(MaritimeEvent.event_date.desc()).limit(limit).offset(offset)
    result = await session.execute(stmt)
    rows = result.scalars().all()

    items = [
        {
            "id": e.id,
            "event_type": e.event_type,
            "title": e.title,
            "description": e.description,
            "location": e.location,
            "severity": e.severity,
            "event_date": e.event_date.isoformat() if e.event_date else None,
            "source": e.source,
            "source_url": e.source_url,
            "extraction_confidence": e.extraction_confidence,
            "verification_status": e.verification_status,
        }
        for e in rows
    ]
    return {"items": items, "page": page, "page_size": page_size, "total": total}


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------

async def add_to_watchlist(
    session: AsyncSession,
    *,
    group_id: str,
    actor_id: str = DEFAULT_ACTOR,
    note: Optional[str] = None,
) -> Watchlist:
    """Add a group to the watchlist (idempotent)."""
    result = await session.execute(
        select(Watchlist).where(
            and_(Watchlist.group_id == group_id, Watchlist.actor_id == actor_id)
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        if note is not None:
            existing.note = note
        return existing

    entry = Watchlist(
        actor_id=actor_id,
        group_id=group_id,
        note=note,
    )
    session.add(entry)
    await session.flush()
    return entry


async def remove_from_watchlist(
    session: AsyncSession,
    *,
    group_id: str,
    actor_id: str = DEFAULT_ACTOR,
) -> bool:
    """Remove a group from the watchlist. Returns True if removed."""
    result = await session.execute(
        delete(Watchlist).where(
            and_(Watchlist.group_id == group_id, Watchlist.actor_id == actor_id)
        )
    )
    return result.rowcount > 0  # type: ignore


# ---------------------------------------------------------------------------
# APT Alias
# ---------------------------------------------------------------------------

async def upsert_apt_alias(
    session: AsyncSession,
    *,
    alias_name: str,
    group_id: Optional[str] = None,
    naming_org: Optional[str] = None,
    confidence: float = 0.9,
    source_url: Optional[str] = None,
) -> AptAlias:
    """Upsert an APT alias by (lower(alias_name), naming_org)."""
    result = await session.execute(
        select(AptAlias).where(
            and_(
                func.lower(AptAlias.alias_name) == alias_name.lower(),
                AptAlias.naming_org == naming_org,
            )
        )
    )
    existing = result.scalar_one_or_none()

    if existing is not None:
        if group_id is not None:
            existing.group_id = group_id
        existing.confidence = max(existing.confidence, confidence)
        if source_url is not None:
            existing.source_url = source_url
        return existing

    alias = AptAlias(
        group_id=group_id,
        alias_name=alias_name,
        naming_org=naming_org,
        confidence=confidence,
        source_url=source_url,
    )
    session.add(alias)
    await session.flush()
    return alias


# ---------------------------------------------------------------------------
# Feed Pull Run
# ---------------------------------------------------------------------------

async def create_feed_pull_run(
    session: AsyncSession,
    *,
    source: str,
    trigger: str = "manual",
) -> FeedPullRun:
    """Create a new feed pull run record with status=running."""
    run = FeedPullRun(
        id=generate_ulid(),
        source=source,
        trigger=trigger,
        status="running",
    )
    session.add(run)
    await session.flush()
    return run


async def finish_feed_pull_run(
    session: AsyncSession,
    *,
    run_id: str,
    status: str,
    inserted_count: int = 0,
    updated_count: int = 0,
    skipped_count: int = 0,
    unmapped_count: int = 0,
    error_message: Optional[str] = None,
    metadata_json: Optional[dict] = None,
) -> Optional[FeedPullRun]:
    """Mark a feed pull run as finished with final counts."""
    result = await session.execute(
        select(FeedPullRun).where(FeedPullRun.id == run_id)
    )
    run = result.scalar_one_or_none()
    if run is None:
        return None

    run.status = status
    run.finished_at = _utcnow()
    run.inserted_count = inserted_count
    run.updated_count = updated_count
    run.skipped_count = skipped_count
    run.unmapped_count = unmapped_count
    run.error_message = error_message
    run.metadata_json = metadata_json
    return run


async def list_feed_pull_runs(
    session: AsyncSession,
    *,
    source: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """List feed pull runs with pagination and filters."""
    limit, offset = _paginate(page, page_size)
    stmt = select(FeedPullRun)

    if source:
        stmt = stmt.where(FeedPullRun.source == source)
    if status:
        stmt = stmt.where(FeedPullRun.status == status)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await session.execute(count_stmt)).scalar() or 0

    stmt = stmt.order_by(FeedPullRun.started_at.desc()).limit(limit).offset(offset)
    result = await session.execute(stmt)
    rows = result.scalars().all()

    items = [
        {
            "id": r.id,
            "source": r.source,
            "trigger": r.trigger,
            "status": r.status,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "inserted_count": r.inserted_count,
            "updated_count": r.updated_count,
            "skipped_count": r.skipped_count,
            "unmapped_count": r.unmapped_count,
            "error_message": r.error_message,
        }
        for r in rows
    ]
    return {"items": items, "page": page, "page_size": page_size, "total": total}


# ---------------------------------------------------------------------------
# Overview Statistics
# ---------------------------------------------------------------------------

async def get_overview(
    session: AsyncSession,
    *,
    actor_id: str = DEFAULT_ACTOR,
) -> dict[str, Any]:
    """Compute the overview dashboard data.

    Returns 5 card sections + freshness data, matching PRD §6.3.
    """
    now = _utcnow()
    seven_days_ago = now - timedelta(days=7)

    # 1. Freshness — last successful feed run per source
    freshness_sources = await session.execute(
        select(
            FeedPullRun.source,
            func.max(FeedPullRun.finished_at).label("last_success"),
        )
        .where(FeedPullRun.status.in_(["ok", "partial"]))
        .group_by(FeedPullRun.source)
    )
    freshness_map = {
        row.source: row.last_success for row in freshness_sources
    }

    # Failed sources (last run failed)
    failed_result = await session.execute(
        select(FeedPullRun.source, FeedPullRun.status, FeedPullRun.finished_at)
        .where(FeedPullRun.status == "failed")
        .order_by(FeedPullRun.finished_at.desc())
    )
    failed_sources_set: set[str] = set()
    latest_status: dict[str, str] = {}
    for row in failed_result:
        if row.source not in latest_status:
            latest_status[row.source] = row.status
            if row.status == "failed":
                failed_sources_set.add(row.source)

    last_success_at = max(freshness_map.values()) if freshness_map else None

    # Stale sources: last success > 48h ago or no success
    stale_sources = []
    for src, last_ok in freshness_map.items():
        if last_ok is None or (now - last_ok).total_seconds() > 48 * 3600:
            stale_sources.append(src)

    # 2. Watched groups activity
    watched_groups = await session.execute(
        select(Watchlist.group_id).where(Watchlist.actor_id == actor_id)
    )
    watched_ids = [row[0] for row in watched_groups]

    watched_activities = []
    recent_activity_count = 0

    if watched_ids:
        # New C2 IPs for watched groups in last 7 days
        new_ips_result = await session.execute(
            select(ThreatInfraIP.group_id, func.count().label("cnt"), func.max(ThreatInfraIP.last_ingested_at).label("ts"))
            .where(
                and_(
                    ThreatInfraIP.group_id.in_(watched_ids),
                    ThreatInfraIP.last_ingested_at >= seven_days_ago,
                )
            )
            .group_by(ThreatInfraIP.group_id)
        )
        for row in new_ips_result:
            group_name_result = await session.execute(
                select(ThreatGroup.name).where(ThreatGroup.id == row.group_id)
            )
            group_name = group_name_result.scalar() or "Unknown"
            watched_activities.append({
                "group_id": row.group_id,
                "group_name": group_name,
                "activity_type": "new_c2_ip",
                "count": row.cnt,
                "timestamp": row.ts.isoformat() if row.ts else None,
            })
            recent_activity_count += 1

        # New malware for watched groups
        new_malware_result = await session.execute(
            select(ThreatMalwareFamily.group_id, func.count().label("cnt"), func.max(ThreatMalwareFamily.last_ingested_at).label("ts"))
            .where(
                and_(
                    ThreatMalwareFamily.group_id.in_(watched_ids),
                    ThreatMalwareFamily.last_ingested_at >= seven_days_ago,
                )
            )
            .group_by(ThreatMalwareFamily.group_id)
        )
        for row in new_malware_result:
            group_name_result = await session.execute(
                select(ThreatGroup.name).where(ThreatGroup.id == row.group_id)
            )
            group_name = group_name_result.scalar() or "Unknown"
            watched_activities.append({
                "group_id": row.group_id,
                "group_name": group_name,
                "activity_type": "new_malware",
                "count": row.cnt,
                "timestamp": row.ts.isoformat() if row.ts else None,
            })
            recent_activity_count += 1

    # 3. High severity vulns
    total_vulns = (await session.execute(
        select(func.count()).select_from(ThreatVuln)
    )).scalar() or 0

    new_vulns_7d = (await session.execute(
        select(func.count()).select_from(ThreatVuln)
        .where(ThreatVuln.last_ingested_at >= seven_days_ago)
    )).scalar() or 0

    supply_chain_count = (await session.execute(
        select(func.count()).select_from(ThreatVuln)
        .where(ThreatVuln.is_supply_chain == True)  # noqa: E712
    )).scalar() or 0

    # Trend: compare last 7 days vs previous 7 days
    prev_7d = seven_days_ago - timedelta(days=7)
    prev_vulns = (await session.execute(
        select(func.count()).select_from(ThreatVuln)
        .where(
            and_(
                ThreatVuln.last_ingested_at >= prev_7d,
                ThreatVuln.last_ingested_at < seven_days_ago,
            )
        )
    )).scalar() or 0

    trend = "up" if new_vulns_7d > prev_vulns else ("down" if new_vulns_7d < prev_vulns else "stable")

    # 4. Active C2 IPs
    total_c2 = (await session.execute(
        select(func.count()).select_from(ThreatInfraIP)
        .where(ThreatInfraIP.status == "active")
    )).scalar() or 0

    c2_by_group_result = await session.execute(
        select(ThreatGroup.name, func.count().label("cnt"))
        .join(ThreatInfraIP, ThreatInfraIP.group_id == ThreatGroup.id)
        .where(ThreatInfraIP.status == "active")
        .group_by(ThreatGroup.id, ThreatGroup.name)
        .order_by(func.count().desc())
        .limit(3)
    )
    c2_by_group = [{"group_name": row.name, "count": row.cnt} for row in c2_by_group_result]

    # 5. Maritime events
    total_maritime = (await session.execute(
        select(func.count()).select_from(MaritimeEvent)
    )).scalar() or 0

    recent_maritime = (await session.execute(
        select(MaritimeEvent)
        .where(MaritimeEvent.event_date >= seven_days_ago)
        .order_by(MaritimeEvent.event_date.desc())
        .limit(1)
    )).scalar_one_or_none()

    # 6. Malware activity
    total_families = (await session.execute(
        select(func.count()).select_from(ThreatMalwareFamily)
    )).scalar() or 0

    top_families_result = await session.execute(
        select(
            ThreatMalwareFamily.family_name,
            ThreatGroup.name,
            func.json_array_length(ThreatMalwareFamily.sample_hashes).label("sample_count"),
        )
        .join(ThreatGroup, ThreatMalwareFamily.group_id == ThreatGroup.id)
        .order_by(func.json_array_length(ThreatMalwareFamily.sample_hashes).desc())
        .limit(5)
    )
    top_families = [
        {"family": row.family_name, "group": row.name, "sample_count": row.sample_count or 0}
        for row in top_families_result
    ]

    return {
        "freshness": {
            "last_success_at": last_success_at.isoformat() if last_success_at else None,
            "stale_sources": stale_sources,
            "failed_sources": list(failed_sources_set),
        },
        "watched_groups_activity": {
            "total_watched": len(watched_ids),
            "recent_activity_count": recent_activity_count,
            "activities": watched_activities[:20],  # Cap at 20 entries
        },
        "high_severity_vulns": {
            "total": total_vulns,
            "new_last_7d": new_vulns_7d,
            "supply_chain_count": supply_chain_count,
            "trend": trend,
        },
        "active_c2_ips": {
            "total": total_c2,
            "by_group": c2_by_group,
        },
        "maritime_events": {
            "total": total_maritime,
            "recent_count": (await session.execute(
                select(func.count()).select_from(MaritimeEvent)
                .where(MaritimeEvent.event_date >= seven_days_ago)
            )).scalar() or 0,
            "latest": {
                "title": recent_maritime.title,
                "event_date": recent_maritime.event_date.isoformat() if recent_maritime else None,
                "severity": recent_maritime.severity if recent_maritime else None,
            } if recent_maritime else None,
        },
        "malware_activity": {
            "total_families": total_families,
            "recent_samples_7d": 0,  # P0: no sample-based counting
            "top_families": top_families,
        },
    }


# ---------------------------------------------------------------------------
# Table creation (for tests / first-run without Alembic)
# ---------------------------------------------------------------------------

async def create_tables() -> None:
    """Create all tables (for first-run or tests without Alembic).

    In production, use Alembic migrations instead.
    """
    from secbot.threat_intel.db import get_engine
    from secbot.threat_intel.models import Base

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

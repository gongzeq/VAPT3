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
    RansomwareEvent,
    ThreatGroup,
    ThreatGroupVulnAssoc,
    ThreatInfraIP,
    ThreatInfraURL,
    ThreatIntelConfig,
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


def _ensure_utc(dt: datetime) -> datetime:
    """Treat naive datetimes (e.g. read back from SQLite) as UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


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

    # Related URLs (Gap 7)
    urls_result = await session.execute(
        select(ThreatInfraURL).where(ThreatInfraURL.group_id == group_id)
    )
    urls = urls_result.scalars().all()

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
        "infra_urls": [
            {
                "id": u.id,
                "url": u.url,
                "url_type": u.url_type,
                "malware_family": u.malware_family,
                "threat_type": u.threat_type,
                "geo_country": u.geo_country,
                "host": u.host,
                "first_seen": u.first_seen.isoformat() if u.first_seen else None,
                "last_seen": u.last_seen.isoformat() if u.last_seen else None,
                "status": u.status,
                "source": u.source,
                "confidence": u.confidence,
            }
            for u in urls
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
    else:
        # Default: exclude archived IPs
        stmt = stmt.where(ThreatInfraIP.status != "archived")
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
) -> tuple[AptAlias, bool]:
    """Upsert an APT alias by (lower(alias_name), naming_org).

    Returns (alias, created) where *created* is True when a new row was
    inserted and False when an existing row was updated.
    """
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
        return existing, False

    alias = AptAlias(
        group_id=group_id,
        alias_name=alias_name,
        naming_org=naming_org,
        confidence=confidence,
        source_url=source_url,
    )
    session.add(alias)
    await session.flush()
    return alias, True


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
    """Mark a feed pull run as finished with final counts.

    When ``status == "failed"``, broadcasts a ``threat_intel_feed_failed``
    WebSocket event to all connected clients so the frontend can show a
    dismissible toast notification. ``status == "partial"`` does NOT trigger
    the broadcast.
    """
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

    # Broadcast failure event via WebSocket (best-effort, non-blocking)
    if status == "failed":
        try:
            from secbot.channels.websocket import WebSocketChannel

            ws = WebSocketChannel.get_active_instance()
            if ws is not None:
                from datetime import datetime as _dt

                body = {
                    "event": "agent_event",
                    "chat_id": "",
                    "type": "threat_intel_feed_failed",
                    "payload": {
                        "type": "threat_intel_feed_failed",
                        "source": run.source,
                        "run_id": run_id,
                        "error_message": error_message or "Unknown error",
                        "started_at": run.started_at.isoformat() if run.started_at else None,
                        "failed_at": _utcnow().isoformat(),
                    },
                    "timestamp": _dt.now().astimezone().isoformat(timespec="seconds"),
                }
                await ws._broadcast_frame(body, chat_id=None)
        except Exception:
            _logger.warning(
                "Failed to broadcast feed failure event for run %s",
                run_id,
                exc_info=True,
            )

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

    last_success_at = (
        max(_ensure_utc(v) for v in freshness_map.values()) if freshness_map else None
    )

    # Stale sources: last success > 48h ago or no success
    stale_sources = []
    for src, last_ok in freshness_map.items():
        if last_ok is None or (now - _ensure_utc(last_ok)).total_seconds() > 48 * 3600:
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

    # 7. Malicious URLs (Gap 4)
    total_urls = (await session.execute(
        select(func.count()).select_from(ThreatInfraURL)
        .where(ThreatInfraURL.status != "archived")
    )).scalar() or 0

    urls_by_source_result = await session.execute(
        select(ThreatInfraURL.source, func.count().label("cnt"))
        .where(ThreatInfraURL.status != "archived")
        .group_by(ThreatInfraURL.source)
        .order_by(func.count().desc())
        .limit(5)
    )
    urls_by_source = [{"source": row.source, "count": row.cnt} for row in urls_by_source_result]

    # 8. Ransomware events (Gap 4)
    total_ransomware = (await session.execute(
        select(func.count()).select_from(RansomwareEvent)
    )).scalar() or 0

    recent_ransomware = (await session.execute(
        select(RansomwareEvent)
        .where(RansomwareEvent.breach_date >= seven_days_ago)
        .order_by(RansomwareEvent.breach_date.desc())
        .limit(1)
    )).scalar_one_or_none()

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
        "malicious_urls": {
            "total": total_urls,
            "by_source": urls_by_source,
        },
        "ransomware_events": {
            "total": total_ransomware,
            "recent_count": (await session.execute(
                select(func.count()).select_from(RansomwareEvent)
                .where(RansomwareEvent.breach_date >= seven_days_ago)
            )).scalar() or 0,
            "latest": {
                "victim_name": recent_ransomware.victim_name if recent_ransomware else None,
                "group_name": recent_ransomware.group_name if recent_ransomware else None,
                "breach_date": recent_ransomware.breach_date.isoformat() if recent_ransomware and recent_ransomware.breach_date else None,
                "severity": recent_ransomware.severity if recent_ransomware else None,
            } if recent_ransomware else None,
        },
    }


# ---------------------------------------------------------------------------
# Graph Aggregation API (P1)
# ---------------------------------------------------------------------------

async def get_graph_data(
    session: AsyncSession,
    *,
    group_id: Optional[str] = None,
    watched: bool = False,
    all_mode: bool = False,
    group_ids: Optional[list[str]] = None,
    actor_id: str = DEFAULT_ACTOR,
    top_n: int = 30,
    min_confidence: float = 0.0,
    node_types: Optional[list[str]] = None,
    expand_cluster: Optional[str] = None,
) -> dict[str, Any]:
    """Build knowledge graph data: nodes + edges with merging and clustering.

    Modes (exactly one):
    - group_id: single-group local graph
    - watched=True: all Watchlist groups global graph
    - all_mode=True: all groups with satellite data (malware/IP/vuln)
    - group_ids: multi-group comparison graph
    """
    # Determine target group IDs
    target_group_ids: list[str] = []

    if group_id:
        target_group_ids = [group_id]
    elif all_mode:
        # "全部" mode: find all groups that have satellite data
        # Query groups with malware families
        result = await session.execute(
            select(ThreatMalwareFamily.group_id).distinct()
        )
        malware_gids = {row[0] for row in result}
        # Query groups with IPs
        result = await session.execute(
            select(ThreatInfraIP.group_id).distinct()
        )
        ip_gids = {row[0] for row in result}
        # Query groups with vuln associations
        result = await session.execute(
            select(ThreatGroupVulnAssoc.group_id).distinct()
        )
        vuln_gids = {row[0] for row in result}
        # Query groups with URLs
        result = await session.execute(
            select(ThreatInfraURL.group_id).distinct()
        )
        url_gids = {row[0] for row in result if row[0] is not None}
        target_group_ids = list(malware_gids | ip_gids | vuln_gids | url_gids)
    elif watched:
        result = await session.execute(
            select(Watchlist.group_id).where(Watchlist.actor_id == actor_id)
        )
        target_group_ids = [row.group_id for row in result]
    elif group_ids:
        target_group_ids = group_ids

    if not target_group_ids:
        return {"nodes": [], "edges": [], "metadata": {
            "total_nodes": 0, "total_edges": 0,
            "clustered_nodes": 0, "groups_included": 0,
        }}

    # Fetch groups
    result = await session.execute(
        select(ThreatGroup).where(ThreatGroup.id.in_(target_group_ids))
    )
    groups = {g.id: g for g in result.scalars()}

    # Fetch watched set
    watched_result = await session.execute(
        select(Watchlist.group_id).where(Watchlist.actor_id == actor_id)
    )
    watched_set = {row.group_id for row in watched_result}

    # Expand cluster mode: return only expanded nodes
    if expand_cluster and group_id:
        return await _expand_cluster_nodes(
            session, group_id=group_id, cluster_type=expand_cluster,
        )

    nodes: list[dict] = []
    edges: list[dict] = []

    # Add group nodes
    for gid, g in groups.items():
        nodes.append({
            "id": g.id,
            "type": "group",
            "label": g.name,
            "data": {
                "mitre_id": g.mitre_id,
                "origin_country": g.origin_country,
                "is_watched": gid in watched_set,
            },
        })

    # Fetch and process IPs
    ip_filter = [ThreatInfraIP.group_id.in_(target_group_ids)]
    if node_types and "ip" not in node_types:
        ip_filter = []  # Skip IPs

    if ip_filter:
        result = await session.execute(
            select(ThreatInfraIP)
            .where(and_(*ip_filter))
            .where(ThreatInfraIP.status != "archived")
        )
        all_ips = result.scalars().all()

        # Node merging: same IP address -> single node
        ip_merge_map: dict[str, str] = {}
        group_ip_counts: dict[str, int] = {}

        for ip in all_ips:
            if ip.group_id not in group_ip_counts:
                group_ip_counts[ip.group_id] = 0
            group_ip_counts[ip.group_id] += 1

            if ip.ip_address not in ip_merge_map:
                ip_merge_map[ip.ip_address] = ip.id

        # Clustering: if group has > top_n IPs, create cluster node
        clustered_groups: set[str] = set()
        for gid, count in group_ip_counts.items():
            if count > top_n:
                cluster_node = {
                    "id": f"cluster:ip:{gid}",
                    "type": "cluster",
                    "label": f"C2 IP x {count}",
                    "data": {"cluster_type": "ip", "count": count, "group_id": gid},
                }
                nodes.append(cluster_node)
                edges.append({
                    "source": gid, "target": cluster_node["id"],
                    "type": "uses_c2", "confidence": 1.0,
                })
                clustered_groups.add(gid)

        # Add non-clustered IP nodes + edges
        added_ip_nodes: set[str] = set()
        for ip in all_ips:
            if ip.group_id in clustered_groups:
                continue
            canonical_id = ip_merge_map[ip.ip_address]
            if canonical_id not in added_ip_nodes:
                nodes.append({
                    "id": canonical_id,
                    "type": "ip",
                    "label": ip.ip_address,
                    "data": {
                        "ip_type": ip.ip_type,
                        "status": ip.status,
                        "geo_country": ip.geo_country,
                        "malware_family": ip.malware_family,
                    },
                })
                added_ip_nodes.add(canonical_id)
            edges.append({
                "source": ip.group_id,
                "target": canonical_id,
                "type": "uses_c2",
                "confidence": ip.confidence,
            })

    # Fetch and process malware
    if not node_types or "malware" in node_types:
        result = await session.execute(
            select(ThreatMalwareFamily)
            .where(ThreatMalwareFamily.group_id.in_(target_group_ids))
        )
        all_malware = result.scalars().all()

        malware_merge_map: dict[str, str] = {}
        group_malware_counts: dict[str, int] = {}

        for m in all_malware:
            key = m.family_name.lower()
            if m.group_id not in group_malware_counts:
                group_malware_counts[m.group_id] = 0
            group_malware_counts[m.group_id] += 1
            if key not in malware_merge_map:
                malware_merge_map[key] = m.id

        clustered_malware_groups: set[str] = set()
        for gid, count in group_malware_counts.items():
            if count > top_n:
                cluster_node = {
                    "id": f"cluster:malware:{gid}",
                    "type": "cluster",
                    "label": f"Malware x {count}",
                    "data": {"cluster_type": "malware", "count": count, "group_id": gid},
                }
                nodes.append(cluster_node)
                edges.append({
                    "source": gid, "target": cluster_node["id"],
                    "type": "uses_malware", "confidence": 1.0,
                })
                clustered_malware_groups.add(gid)

        added_malware_nodes: set[str] = set()
        for m in all_malware:
            if m.group_id in clustered_malware_groups:
                continue
            canonical_id = malware_merge_map[m.family_name.lower()]
            if canonical_id not in added_malware_nodes:
                nodes.append({
                    "id": canonical_id,
                    "type": "malware",
                    "label": m.family_name,
                    "data": {
                        "type": m.type,
                        "platform": m.platform,
                    },
                })
                added_malware_nodes.add(canonical_id)
            edges.append({
                "source": m.group_id,
                "target": canonical_id,
                "type": "uses_malware",
                "confidence": m.confidence,
            })

    # Fetch and process vulnerabilities (via group associations)
    if not node_types or "vuln" in node_types:
        result = await session.execute(
            select(ThreatGroupVulnAssoc, ThreatVuln)
            .join(ThreatVuln, ThreatGroupVulnAssoc.vulnerability_id == ThreatVuln.id)
            .where(ThreatGroupVulnAssoc.group_id.in_(target_group_ids))
        )
        all_vuln_assocs = result.all()

        added_vuln_nodes: set[str] = set()
        for assoc, vuln in all_vuln_assocs:
            if vuln.id not in added_vuln_nodes:
                nodes.append({
                    "id": vuln.id,
                    "type": "vuln",
                    "label": vuln.cve_id,
                    "data": {
                        "cvss_score": vuln.cvss_score,
                        "severity": vuln.severity,
                        "is_cisa_kev": vuln.is_cisa_kev,
                        "is_supply_chain": vuln.is_supply_chain,
                    },
                })
                added_vuln_nodes.add(vuln.id)

            edge_type = "exploits" if assoc.relationship_type == "exploited" else "targets"
            edges.append({
                "source": assoc.group_id,
                "target": vuln.id,
                "type": edge_type,
                "confidence": assoc.confidence,
            })

    # Fetch and process URLs (Gap 6)
    if not node_types or "url" in node_types:
        result = await session.execute(
            select(ThreatInfraURL)
            .where(ThreatInfraURL.group_id.in_(target_group_ids))
            .where(ThreatInfraURL.status != "archived")
        )
        all_urls = result.scalars().all()

        url_merge_map: dict[str, str] = {}
        group_url_counts: dict[str, int] = {}

        for u in all_urls:
            if u.group_id is None:
                continue
            if u.group_id not in group_url_counts:
                group_url_counts[u.group_id] = 0
            group_url_counts[u.group_id] += 1
            if u.url not in url_merge_map:
                url_merge_map[u.url] = u.id

        clustered_url_groups: set[str] = set()
        for gid, count in group_url_counts.items():
            if count > top_n:
                cluster_node = {
                    "id": f"cluster:url:{gid}",
                    "type": "cluster",
                    "label": f"URL x {count}",
                    "data": {"cluster_type": "url", "count": count, "group_id": gid},
                }
                nodes.append(cluster_node)
                edges.append({
                    "source": gid, "target": cluster_node["id"],
                    "type": "targets", "confidence": 1.0,
                })
                clustered_url_groups.add(gid)

        added_url_nodes: set[str] = set()
        for u in all_urls:
            if u.group_id is None or u.group_id in clustered_url_groups:
                continue
            canonical_id = url_merge_map[u.url]
            if canonical_id not in added_url_nodes:
                nodes.append({
                    "id": canonical_id,
                    "type": "url",
                    "label": u.host or u.url[:40],
                    "data": {
                        "url": u.url,
                        "url_type": u.url_type,
                        "status": u.status,
                        "source": u.source,
                    },
                })
                added_url_nodes.add(canonical_id)
            edges.append({
                "source": u.group_id,
                "target": canonical_id,
                "type": "targets",
                "confidence": u.confidence,
            })

    # Apply confidence filter
    edges = [e for e in edges if e["confidence"] >= min_confidence]

    # Remove orphaned non-group nodes
    connected_ids = {e["source"] for e in edges} | {e["target"] for e in edges}
    nodes = [n for n in nodes if n["id"] in connected_ids or n["type"] == "group"]

    clustered_count = sum(1 for n in nodes if n["type"] == "cluster")

    return {
        "nodes": nodes,
        "edges": edges,
        "metadata": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "clustered_nodes": clustered_count,
            "groups_included": len(target_group_ids),
        },
    }


async def _expand_cluster_nodes(
    session: AsyncSession,
    *,
    group_id: str,
    cluster_type: str,
) -> dict[str, Any]:
    """Expand a cluster node into its real sub-nodes."""
    nodes: list[dict] = []
    edges: list[dict] = []

    if cluster_type == "ip":
        result = await session.execute(
            select(ThreatInfraIP)
            .where(ThreatInfraIP.group_id == group_id)
            .where(ThreatInfraIP.status != "archived")
        )
        for ip in result.scalars():
            nodes.append({
                "id": ip.id,
                "type": "ip",
                "label": ip.ip_address,
                "data": {
                    "ip_type": ip.ip_type,
                    "status": ip.status,
                    "geo_country": ip.geo_country,
                    "malware_family": ip.malware_family,
                },
            })
            edges.append({
                "source": group_id,
                "target": ip.id,
                "type": "uses_c2",
                "confidence": ip.confidence,
            })

    elif cluster_type == "malware":
        result = await session.execute(
            select(ThreatMalwareFamily)
            .where(ThreatMalwareFamily.group_id == group_id)
        )
        for m in result.scalars():
            nodes.append({
                "id": m.id,
                "type": "malware",
                "label": m.family_name,
                "data": {"type": m.type, "platform": m.platform},
            })
            edges.append({
                "source": group_id,
                "target": m.id,
                "type": "uses_malware",
                "confidence": m.confidence,
            })

    return {
        "nodes": nodes,
        "edges": edges,
        "metadata": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "clustered_nodes": 0,
            "groups_included": 1,
        },
    }


# ---------------------------------------------------------------------------
# Detail API functions (P1)
# ---------------------------------------------------------------------------

async def get_threat_vuln(session: AsyncSession, vuln_id: str) -> Optional[dict]:
    """Get full vulnerability detail by ID."""
    result = await session.execute(
        select(ThreatVuln).where(ThreatVuln.id == vuln_id)
    )
    vuln = result.scalar_one_or_none()
    if vuln is None:
        return None

    # Fetch exploiting groups
    assoc_result = await session.execute(
        select(ThreatGroupVulnAssoc, ThreatGroup)
        .join(ThreatGroup, ThreatGroupVulnAssoc.group_id == ThreatGroup.id)
        .where(ThreatGroupVulnAssoc.vulnerability_id == vuln_id)
    )
    exploiting_groups = [
        {
            "group_id": assoc.group_id,
            "group_name": group.name,
            "relationship_type": assoc.relationship_type,
            "confidence": assoc.confidence,
            "last_seen": assoc.last_seen.isoformat() if assoc.last_seen else None,
        }
        for assoc, group in assoc_result
    ]

    return {
        "id": vuln.id,
        "cve_id": vuln.cve_id,
        "title": vuln.title,
        "description": vuln.description,
        "cvss_score": vuln.cvss_score,
        "severity": vuln.severity,
        "affected_products": vuln.affected_products or [],
        "is_supply_chain": vuln.is_supply_chain,
        "has_poc": vuln.has_poc,
        "exploit_available": vuln.exploit_available,
        "is_cisa_kev": vuln.is_cisa_kev,
        "cisa_kev_date": vuln.cisa_kev_date.isoformat() if vuln.cisa_kev_date else None,
        "published_date": vuln.published_date.isoformat() if vuln.published_date else None,
        "primary_source": vuln.primary_source,
        "sources": vuln.sources or [],
        "source_refs": vuln.source_refs or [],
        "tags": vuln.tags or [],
        "exploiting_groups": exploiting_groups,
        "last_ingested_at": vuln.last_ingested_at.isoformat() if vuln.last_ingested_at else None,
        "created_at": vuln.created_at.isoformat() if vuln.created_at else None,
        "updated_at": vuln.updated_at.isoformat() if vuln.updated_at else None,
    }


async def get_threat_infra_ip_detail(session: AsyncSession, ip_id: str) -> Optional[dict]:
    """Get full infrastructure IP detail by ID."""
    result = await session.execute(
        select(ThreatInfraIP, ThreatGroup.name)
        .join(ThreatGroup, ThreatInfraIP.group_id == ThreatGroup.id)
        .where(ThreatInfraIP.id == ip_id)
    )
    row = result.first()
    if row is None:
        return None

    ip, group_name = row
    return {
        "id": ip.id,
        "group_id": ip.group_id,
        "group_name": group_name,
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
        "source_refs": ip.source_refs or [],
        "tags": ip.tags or [],
        "last_ingested_at": ip.last_ingested_at.isoformat() if ip.last_ingested_at else None,
        "created_at": ip.created_at.isoformat() if ip.created_at else None,
    }


async def get_threat_malware_detail(session: AsyncSession, malware_id: str) -> Optional[dict]:
    """Get full malware family detail by ID."""
    result = await session.execute(
        select(ThreatMalwareFamily, ThreatGroup.name)
        .join(ThreatGroup, ThreatMalwareFamily.group_id == ThreatGroup.id)
        .where(ThreatMalwareFamily.id == malware_id)
    )
    row = result.first()
    if row is None:
        return None

    m, group_name = row
    return {
        "id": m.id,
        "group_id": m.group_id,
        "group_name": group_name,
        "family_name": m.family_name,
        "aliases": m.aliases or [],
        "description": m.description,
        "type": m.type,
        "platform": m.platform or [],
        "sample_hashes": m.sample_hashes or [],
        "yara_rules": m.yara_rules or [],
        "first_seen": m.first_seen.isoformat() if m.first_seen else None,
        "last_active": m.last_active.isoformat() if m.last_active else None,
        "source": m.source,
        "confidence": m.confidence,
        "source_refs": m.source_refs or [],
        "tags": m.tags or [],
        "last_ingested_at": m.last_ingested_at.isoformat() if m.last_ingested_at else None,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


# ---------------------------------------------------------------------------
# Data expiry & archival (P2)
# ---------------------------------------------------------------------------

async def run_expiry_sweep(session: AsyncSession) -> dict[str, int]:
    """Run data expiry sweep. Returns counts of archived/deleted records."""
    now = _utcnow()
    archived_ips = 0
    auto_inactive_ips = 0
    deleted_maritime = 0
    deleted_runs = 0

    # 1. Auto-inactive: active IPs not seen in 180 days
    result = await session.execute(
        select(ThreatInfraIP).where(
            and_(
                ThreatInfraIP.status == "active",
                ThreatInfraIP.last_seen < now - timedelta(days=180),
            )
        )
    )
    for ip in result.scalars():
        ip.status = "inactive"
        auto_inactive_ips += 1

    # 2. Archive: inactive IPs not seen in 90 days
    result = await session.execute(
        select(ThreatInfraIP).where(
            and_(
                ThreatInfraIP.status == "inactive",
                ThreatInfraIP.last_seen < now - timedelta(days=90),
            )
        )
    )
    for ip in result.scalars():
        ip.status = "archived"
        archived_ips += 1

    # 3. Delete old dismissed maritime events (>1 year)
    result = await session.execute(
        select(MaritimeEvent).where(
            and_(
                MaritimeEvent.event_date < now - timedelta(days=365),
                MaritimeEvent.verification_status == "dismissed",
            )
        )
    )
    for event in result.scalars():
        await session.delete(event)
        deleted_maritime += 1

    # 4. Delete old feed runs (>90 days)
    result = await session.execute(
        select(FeedPullRun).where(
            FeedPullRun.started_at < now - timedelta(days=90)
        )
    )
    for run in result.scalars():
        await session.delete(run)
        deleted_runs += 1

    # 5. Auto-inactive URLs not seen in 180 days (Gap 8)
    result = await session.execute(
        select(ThreatInfraURL).where(
            and_(
                ThreatInfraURL.status == "active",
                ThreatInfraURL.last_seen < now - timedelta(days=180),
            )
        )
    )
    auto_inactive_urls = 0
    for url in result.scalars():
        url.status = "inactive"
        auto_inactive_urls += 1

    # 6. Archive inactive URLs not seen in 90 days (Gap 8)
    result = await session.execute(
        select(ThreatInfraURL).where(
            and_(
                ThreatInfraURL.status == "inactive",
                ThreatInfraURL.last_seen < now - timedelta(days=90),
            )
        )
    )
    archived_urls = 0
    for url in result.scalars():
        url.status = "archived"
        archived_urls += 1

    # 7. Delete old ransomware events (>1 year) (Gap 8)
    result = await session.execute(
        select(RansomwareEvent).where(
            RansomwareEvent.breach_date < now - timedelta(days=365)
        )
    )
    deleted_ransomware = 0
    for event in result.scalars():
        await session.delete(event)
        deleted_ransomware += 1

    return {
        "auto_inactive_ips": auto_inactive_ips,
        "archived_ips": archived_ips,
        "deleted_maritime": deleted_maritime,
        "deleted_runs": deleted_runs,
        "auto_inactive_urls": auto_inactive_urls,
        "archived_urls": archived_urls,
        "deleted_ransomware": deleted_ransomware,
    }


# ---------------------------------------------------------------------------
# Low-confidence review queue (P2)
# ---------------------------------------------------------------------------

async def get_review_queue(
    session: AsyncSession,
    *,
    entity_type: str = "ip",
    max_confidence: float = 0.65,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """Get low-confidence records for human review."""
    limit, offset = _paginate(page, page_size)
    items: list[dict] = []

    if entity_type == "ip":
        stmt = (
            select(ThreatInfraIP, ThreatGroup.name)
            .join(ThreatGroup, ThreatInfraIP.group_id == ThreatGroup.id)
            .where(ThreatInfraIP.confidence < max_confidence)
            .where(ThreatInfraIP.status != "archived")
            .order_by(ThreatInfraIP.confidence.asc())
        )
        count_stmt = select(func.count()).select_from(
            select(ThreatInfraIP)
            .where(ThreatInfraIP.confidence < max_confidence)
            .where(ThreatInfraIP.status != "archived")
            .subquery()
        )
        total = (await session.execute(count_stmt)).scalar() or 0

        result = await session.execute(stmt.limit(limit).offset(offset))
        for ip, group_name in result:
            items.append({
                "id": ip.id,
                "entity_type": "ip",
                "label": ip.ip_address,
                "confidence": ip.confidence,
                "group_id": ip.group_id,
                "group_name": group_name,
                "source": ip.source,
                "source_refs": ip.source_refs or [],
                "review_action": "confirm_mapping",
            })

    elif entity_type == "maritime":
        stmt = (
            select(MaritimeEvent)
            .where(MaritimeEvent.extraction_confidence < max_confidence)
            .where(MaritimeEvent.verification_status == "unreviewed")
            .order_by(MaritimeEvent.extraction_confidence.asc())
        )
        count_stmt = select(func.count()).select_from(
            select(MaritimeEvent)
            .where(MaritimeEvent.extraction_confidence < max_confidence)
            .where(MaritimeEvent.verification_status == "unreviewed")
            .subquery()
        )
        total = (await session.execute(count_stmt)).scalar() or 0

        result = await session.execute(stmt.limit(limit).offset(offset))
        for event in result.scalars():
            items.append({
                "id": event.id,
                "entity_type": "maritime",
                "label": event.title,
                "confidence": event.extraction_confidence,
                "group_id": None,
                "group_name": None,
                "source": event.source,
                "source_refs": event.source_refs or [],
                "review_action": "confirm_event",
            })
    elif entity_type == "url":
        # Low-confidence URL group attribution (Gap 9)
        stmt = (
            select(ThreatInfraURL, ThreatGroup.name)
            .outerjoin(ThreatGroup, ThreatInfraURL.group_id == ThreatGroup.id)
            .where(ThreatInfraURL.confidence < max_confidence)
            .where(ThreatInfraURL.status != "archived")
            .order_by(ThreatInfraURL.confidence.asc())
        )
        count_stmt = select(func.count()).select_from(
            select(ThreatInfraURL)
            .where(ThreatInfraURL.confidence < max_confidence)
            .where(ThreatInfraURL.status != "archived")
            .subquery()
        )
        total = (await session.execute(count_stmt)).scalar() or 0

        result = await session.execute(stmt.limit(limit).offset(offset))
        for url, group_name in result:
            items.append({
                "id": url.id,
                "entity_type": "url",
                "label": url.url,
                "confidence": url.confidence,
                "group_id": url.group_id,
                "group_name": group_name,
                "source": url.source,
                "source_refs": url.source_refs or [],
                "review_action": "confirm_mapping",
            })
    else:
        total = 0

    return {"items": items, "page": page, "page_size": page_size, "total": total}


async def apply_review_action(
    session: AsyncSession,
    *,
    item_id: str,
    action: str,
    body: dict,
) -> Optional[dict]:
    """Apply a review action to a low-confidence record."""
    entity_type = body.get("entity_type", "ip")

    if entity_type == "ip":
        result = await session.execute(
            select(ThreatInfraIP).where(ThreatInfraIP.id == item_id)
        )
        ip = result.scalar_one_or_none()
        if ip is None:
            return None

        if action == "confirm_mapping":
            ip.confidence = max(ip.confidence, 0.8)
        elif action == "remap":
            new_group_id = body.get("new_group_id")
            if not new_group_id:
                return {"id": item_id, "action": action, "updated": False,
                        "error": "new_group_id is required for remap"}
            # Validate target group exists
            grp = (await session.execute(
                select(ThreatGroup.id).where(ThreatGroup.id == new_group_id)
            )).scalar_one_or_none()
            if grp is None:
                return None  # handler translates to 404
            ip.group_id = new_group_id
            ip.confidence = 0.8
        elif action == "dismiss":
            ip.status = "archived"

        return {"id": item_id, "action": action, "updated": True}

    elif entity_type == "url":
        # URL review actions (Gap 9)
        result = await session.execute(
            select(ThreatInfraURL).where(ThreatInfraURL.id == item_id)
        )
        url = result.scalar_one_or_none()
        if url is None:
            return None

        if action == "confirm_mapping":
            url.confidence = max(url.confidence, 0.8)
        elif action == "remap":
            new_group_id = body.get("new_group_id")
            if not new_group_id:
                return {"id": item_id, "action": action, "updated": False,
                        "error": "new_group_id is required for remap"}
            grp = (await session.execute(
                select(ThreatGroup.id).where(ThreatGroup.id == new_group_id)
            )).scalar_one_or_none()
            if grp is None:
                return None
            url.group_id = new_group_id
            url.confidence = 0.8
        elif action == "dismiss":
            url.status = "archived"

        return {"id": item_id, "action": action, "updated": True}

    elif entity_type == "maritime":
        result = await session.execute(
            select(MaritimeEvent).where(MaritimeEvent.id == item_id)
        )
        event = result.scalar_one_or_none()
        if event is None:
            return None

        if action == "confirm_event":
            event.verification_status = "confirmed"
            event.extraction_confidence = max(event.extraction_confidence, 0.8)
        elif action == "dismiss":
            event.verification_status = "dismissed"

        return {"id": item_id, "action": action, "updated": True}

    return None


# ---------------------------------------------------------------------------
# Table creation (for tests / first-run without Alembic)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Threat Infrastructure URL
# ---------------------------------------------------------------------------

async def upsert_threat_infra_url(
    session: AsyncSession,
    *,
    url: str,
    source: str = "urlhaus",
    source_ref: Optional[str] = None,
    group_id: Optional[str] = None,
    url_type: str = "other",
    malware_family: Optional[str] = None,
    threat_type: Optional[str] = None,
    geo_country: Optional[str] = None,
    host: Optional[str] = None,
    first_seen: Optional[datetime] = None,
    last_seen: Optional[datetime] = None,
    status: str = "active",
    confidence: float = 0.7,
    source_refs: Optional[list] = None,
    tags: Optional[list] = None,
) -> tuple[ThreatInfraURL, bool]:
    """Upsert by (source, source_ref) or (source, url)."""
    if source_ref:
        result = await session.execute(
            select(ThreatInfraURL).where(
                and_(
                    ThreatInfraURL.source == source,
                    ThreatInfraURL.source_ref == source_ref,
                )
            )
        )
    else:
        result = await session.execute(
            select(ThreatInfraURL).where(
                and_(
                    ThreatInfraURL.source == source,
                    ThreatInfraURL.url == url,
                )
            )
        )
    existing = result.scalar_one_or_none()

    if existing is not None:
        if malware_family is not None:
            existing.malware_family = malware_family
        if threat_type is not None:
            existing.threat_type = threat_type
        if geo_country is not None:
            existing.geo_country = geo_country
        if host is not None:
            existing.host = host
        if first_seen is not None and (
            existing.first_seen is None or first_seen < _ensure_utc(existing.first_seen)
        ):
            existing.first_seen = first_seen
        if last_seen is not None and (
            existing.last_seen is None or last_seen > _ensure_utc(existing.last_seen)
        ):
            existing.last_seen = last_seen
        existing.status = status
        existing.confidence = max(existing.confidence, confidence)
        if source_refs is not None:
            existing.source_refs = source_refs
        if group_id is not None:
            existing.group_id = group_id
        existing.last_ingested_at = _utcnow()
        return existing, False

    record = ThreatInfraURL(
        id=generate_ulid(),
        group_id=group_id,
        url=url,
        url_type=url_type,
        malware_family=malware_family,
        threat_type=threat_type,
        geo_country=geo_country,
        host=host,
        first_seen=first_seen,
        last_seen=last_seen,
        status=status,
        source=source,
        source_ref=source_ref,
        confidence=confidence,
        source_refs=source_refs,
        tags=tags,
    )
    session.add(record)
    await session.flush()
    return record, True


async def list_threat_infra_urls(
    session: AsyncSession,
    *,
    group_id: Optional[str] = None,
    url_type: Optional[str] = None,
    source: Optional[str] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """List threat infrastructure URLs with pagination and filters."""
    limit, offset = _paginate(page, page_size)
    stmt = select(ThreatInfraURL)

    if group_id:
        stmt = stmt.where(ThreatInfraURL.group_id == group_id)
    if url_type:
        stmt = stmt.where(ThreatInfraURL.url_type == url_type)
    if source:
        stmt = stmt.where(ThreatInfraURL.source == source)
    if status:
        stmt = stmt.where(ThreatInfraURL.status == status)
    else:
        stmt = stmt.where(ThreatInfraURL.status != "archived")
    if q:
        stmt = stmt.where(ThreatInfraURL.url.like(f"%{q}%"))

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await session.execute(count_stmt)).scalar() or 0

    stmt = stmt.order_by(ThreatInfraURL.last_ingested_at.desc()).limit(limit).offset(offset)
    result = await session.execute(stmt)
    rows = result.scalars().all()

    items = [
        {
            "id": u.id,
            "group_id": u.group_id,
            "url": u.url,
            "url_type": u.url_type,
            "malware_family": u.malware_family,
            "threat_type": u.threat_type,
            "geo_country": u.geo_country,
            "host": u.host,
            "first_seen": u.first_seen.isoformat() if u.first_seen else None,
            "last_seen": u.last_seen.isoformat() if u.last_seen else None,
            "status": u.status,
            "source": u.source,
            "confidence": u.confidence,
        }
        for u in rows
    ]
    return {"items": items, "page": page, "page_size": page_size, "total": total}


# ---------------------------------------------------------------------------
# Ransomware Event
# ---------------------------------------------------------------------------

async def upsert_ransomware_event(
    session: AsyncSession,
    *,
    group_name: str,
    victim_name: str,
    source: str = "ransomware_live",
    source_ref: Optional[str] = None,
    victim_industry: Optional[str] = None,
    victim_country: Optional[str] = None,
    description: Optional[str] = None,
    post_url: Optional[str] = None,
    breach_date: Optional[datetime] = None,
    data_leaked: bool = False,
    severity: str = "high",
    source_refs: Optional[list] = None,
    tags: Optional[list] = None,
) -> tuple[RansomwareEvent, bool]:
    """Upsert by (source, source_ref)."""
    if source_ref:
        result = await session.execute(
            select(RansomwareEvent).where(
                and_(
                    RansomwareEvent.source == source,
                    RansomwareEvent.source_ref == source_ref,
                )
            )
        )
        existing = result.scalar_one_or_none()
    elif breach_date is not None:
        # Fallback: match by group + victim + breach_date
        result = await session.execute(
            select(RansomwareEvent).where(
                and_(
                    RansomwareEvent.group_name == group_name,
                    RansomwareEvent.victim_name == victim_name,
                    RansomwareEvent.breach_date == breach_date,
                )
            )
        )
        existing = result.scalar_one_or_none()
    else:
        existing = None

    if existing is not None:
        if victim_industry is not None:
            existing.victim_industry = victim_industry
        if victim_country is not None:
            existing.victim_country = victim_country
        if description is not None:
            existing.description = description
        if post_url is not None:
            existing.post_url = post_url
        if data_leaked:
            existing.data_leaked = True
        existing.severity = severity
        if source_refs is not None:
            existing.source_refs = source_refs
        if tags is not None:
            existing.tags = tags
        existing.last_ingested_at = _utcnow()
        return existing, False

    record = RansomwareEvent(
        id=generate_ulid(),
        group_name=group_name,
        victim_name=victim_name,
        victim_industry=victim_industry,
        victim_country=victim_country,
        description=description,
        post_url=post_url,
        breach_date=breach_date,
        data_leaked=data_leaked,
        severity=severity,
        source=source,
        source_ref=source_ref,
        source_refs=source_refs,
        tags=tags,
    )
    session.add(record)
    await session.flush()
    return record, True


async def list_ransomware_events(
    session: AsyncSession,
    *,
    group_name: Optional[str] = None,
    victim_industry: Optional[str] = None,
    victim_country: Optional[str] = None,
    severity: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """List ransomware events with pagination and filters."""
    limit, offset = _paginate(page, page_size)
    stmt = select(RansomwareEvent)

    if group_name:
        stmt = stmt.where(RansomwareEvent.group_name == group_name)
    if victim_industry:
        stmt = stmt.where(RansomwareEvent.victim_industry == victim_industry)
    if victim_country:
        stmt = stmt.where(RansomwareEvent.victim_country == victim_country)
    if severity:
        stmt = stmt.where(RansomwareEvent.severity == severity)
    if from_date:
        stmt = stmt.where(RansomwareEvent.breach_date >= from_date)
    if to_date:
        stmt = stmt.where(RansomwareEvent.breach_date <= to_date)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await session.execute(count_stmt)).scalar() or 0

    stmt = stmt.order_by(RansomwareEvent.breach_date.desc()).limit(limit).offset(offset)
    result = await session.execute(stmt)
    rows = result.scalars().all()

    items = [
        {
            "id": r.id,
            "group_name": r.group_name,
            "victim_name": r.victim_name,
            "victim_industry": r.victim_industry,
            "victim_country": r.victim_country,
            "description": r.description,
            "post_url": r.post_url,
            "breach_date": r.breach_date.isoformat() if r.breach_date else None,
            "data_leaked": r.data_leaked,
            "severity": r.severity,
            "source": r.source,
        }
        for r in rows
    ]
    return {"items": items, "page": page, "page_size": page_size, "total": total}


# ---------------------------------------------------------------------------
# Table creation (for tests / first-run without Alembic)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# API Key configuration — CRUD for feed API keys stored in DB
# ---------------------------------------------------------------------------

# Default config entries for feeds that use API keys.
_DEFAULT_API_KEY_CONFIGS = [
    {
        "feed_source": "urlhaus",
        "description": "abuse.ch URLhaus API key (required)",
        "is_required": True,
    },
    {
        "feed_source": "nvd",
        "description": "NVD API key (optional, accelerates rate limits)",
        "is_required": False,
    },
    {
        "feed_source": "otx",
        "description": "AlienVault OTX API key (optional, avoids 403 errors)",
        "is_required": False,
    },
]


def _mask_api_key(key: Optional[str]) -> Optional[str]:
    """Mask an API key for display, showing only first 4 and last 4 chars.

    Keys shorter than 17 characters are fully masked to avoid excessive
    information leakage (a 9-char key would otherwise expose 8 of 9 chars).
    """
    if not key:
        return None
    if len(key) <= 16:
        return "****"
    return f"{key[:4]}...{key[-4:]}"


async def get_api_key(session: AsyncSession, feed_source: str) -> Optional[str]:
    """Read and decrypt the API key for a feed source from the config table.

    Returns ``None`` if no key is configured.  Stored values are encrypted
    with Fernet; legacy plaintext values are returned as-is for backward
    compatibility.
    """
    from secbot.threat_intel.crypto import decrypt_api_key

    result = await session.execute(
        select(ThreatIntelConfig.api_key).where(
            ThreatIntelConfig.feed_source == feed_source
        )
    )
    key = result.scalar_one_or_none()
    return decrypt_api_key(key or None)  # type: ignore[arg-type]


async def has_api_key(session: AsyncSession, feed_source: str) -> bool:
    """Check whether an API key is configured for the given feed source."""
    key = await get_api_key(session, feed_source)
    return bool(key)


async def get_all_api_keys(session: AsyncSession) -> list[dict[str, Any]]:
    """List all API key configurations with masked key values.

    Relies on migrations or :func:`create_tables` to seed default rows.
    Returns an empty list if the table is empty (fresh DB without migrations).
    """
    from secbot.threat_intel.crypto import decrypt_api_key

    result = await session.execute(select(ThreatIntelConfig))
    rows = result.scalars().all()

    return [
        {
            "feed_source": row.feed_source,
            "api_key_masked": _mask_api_key(decrypt_api_key(row.api_key)),
            "has_key": bool(row.api_key),
            "description": row.description,
            "is_required": row.is_required,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
        for row in rows
    ]


async def set_api_key(
    session: AsyncSession,
    feed_source: str,
    api_key: str,
    description: Optional[str] = None,
    is_required: Optional[bool] = None,
) -> dict[str, Any]:
    """Set or update an API key for a feed source.

    Uses SQLite upsert (``INSERT ... ON CONFLICT DO UPDATE``) to eliminate
    the TOCTOU race between concurrent callers.  The key is encrypted with
    Fernet before storage.
    """
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    from secbot.threat_intel.crypto import encrypt_api_key

    encrypted = encrypt_api_key(api_key)
    desc = description or f"{feed_source} API key"
    req = is_required if is_required is not None else False

    stmt = sqlite_insert(ThreatIntelConfig).values(
        id=generate_ulid(),
        feed_source=feed_source,
        api_key=encrypted,
        description=desc,
        is_required=req,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["feed_source"],
        set_={
            "api_key": encrypted,
            **({"description": description} if description is not None else {}),
            **({"is_required": is_required} if is_required is not None else {}),
        },
    )
    await session.execute(stmt)
    await session.flush()

    return {
        "feed_source": feed_source,
        "api_key_masked": _mask_api_key(api_key),
        "has_key": True,
        "description": desc,
        "is_required": req,
    }


async def delete_api_key(session: AsyncSession, feed_source: str) -> bool:
    """Clear the API key for a feed source (sets api_key to NULL).

    Returns ``True`` if a row was updated, ``False`` if no config row exists.
    """
    result = await session.execute(
        select(ThreatIntelConfig).where(
            ThreatIntelConfig.feed_source == feed_source
        )
    )
    config = result.scalar_one_or_none()
    if config is None:
        return False
    config.api_key = None
    await session.flush()
    return True


async def migrate_env_api_keys_to_db(session: AsyncSession) -> dict[str, bool]:
    """One-time migration: import API keys from environment variables.

    Checks ``URLHAUS_API_KEY``, ``NVD_API_KEY``, ``OTX_API_KEY`` env vars.
    If a var is set and the corresponding DB config has no key, imports it.
    Returns a dict mapping feed_source → True if a key was imported.
    """
    import os

    env_map = {
        "urlhaus": "URLHAUS_API_KEY",
        "nvd": "NVD_API_KEY",
        "otx": "OTX_API_KEY",
    }
    imported: dict[str, bool] = {}
    for feed_source, env_name in env_map.items():
        env_val = os.environ.get(env_name, "").strip()
        if not env_val:
            continue
        existing = await get_api_key(session, feed_source)
        if existing:
            continue  # DB already has a key — don't overwrite
        await set_api_key(session, feed_source, env_val)
        imported[feed_source] = True
        _logger.warning(
            "Migrated %s from env var %s to DB config. "
            "The environment variable is deprecated and can be removed.",
            feed_source,
            env_name,
        )
    return imported


async def _seed_default_api_key_configs(session: AsyncSession) -> None:
    """Insert default API key config rows using INSERT OR IGNORE.

    Uses SQLite's ``ON CONFLICT DO NOTHING`` to avoid race conditions when
    multiple concurrent sessions attempt to seed simultaneously.
    """
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    for cfg in _DEFAULT_API_KEY_CONFIGS:
        stmt = sqlite_insert(ThreatIntelConfig).values(
            id=generate_ulid(),
            feed_source=cfg["feed_source"],
            api_key=None,
            description=cfg["description"],
            is_required=cfg["is_required"],
        ).on_conflict_do_nothing(index_elements=["feed_source"])
        await session.execute(stmt)
    await session.flush()


async def create_tables() -> None:
    """Create all tables (for first-run or tests without Alembic).

    In production, use Alembic migrations instead.
    """
    from secbot.threat_intel.db import get_engine, get_session
    from secbot.threat_intel.models import Base

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed default API key config entries on fresh databases.
    async with get_session() as session:
        await _seed_default_api_key_configs(session)

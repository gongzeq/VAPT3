"""abuse.ch ThreatFox feed puller.

Fetches recent IOCs from ThreatFox API and maps C2 IPs to ThreatGroup +
ThreatInfraIP records.

P0: C2 IPs must map to an existing ThreatGroup.  Unmapped records
increment ``unmapped_count`` — no pseudo-groups are created.

Data source: https://threatfox.abuse.ch/api/v1/
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import aiohttp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from secbot.threat_intel.models import ThreatGroup
from secbot.threat_intel.repo import (
    create_feed_pull_run,
    finish_feed_pull_run,
    upsert_threat_infra_ip,
)

_logger = logging.getLogger(__name__)

THREATFOX_API_URL = "https://threatfox.abuse.ch/api/v1/"


async def _build_group_lookup(session: AsyncSession) -> dict[str, str]:
    """Build a lookup of lower(name) → group_id and alias → group_id."""
    result = await session.execute(
        select(ThreatGroup.id, ThreatGroup.name, ThreatGroup.aliases)
    )
    lookup: dict[str, str] = {}
    for row in result:
        group_id = row.id
        # Map by lower name
        lookup[row.name.lower()] = group_id
        # Map by lower aliases
        if row.aliases:
            for alias in row.aliases:
                if isinstance(alias, str):
                    lookup[alias.lower()] = group_id
    return lookup


async def _build_malware_to_group_lookup(session: AsyncSession) -> dict[str, str]:
    """Build a lookup of lower(malware_family) → group_id from existing IPs.

    This helps map ThreatFox IOCs where the malware name is known but the
    group association comes from previously mapped IOCs.
    """
    from secbot.threat_intel.models import ThreatInfraIP

    result = await session.execute(
        select(ThreatInfraIP.malware_family, ThreatInfraIP.group_id)
        .where(ThreatInfraIP.malware_family.isnot(None))
        .distinct()
    )
    lookup: dict[str, str] = {}
    for row in result:
        if row.malware_family:
            lookup[row.malware_family.lower()] = row.group_id
    return lookup


async def pull_threatfox(
    session: AsyncSession,
    *,
    trigger: str = "manual",
    days: int = 1,
    url: Optional[str] = None,
) -> dict[str, Any]:
    """Pull ThreatFox IOCs and upsert C2 IPs.

    Returns a summary dict with inserted/updated/skipped/unmapped counts.
    """
    run = await create_feed_pull_run(session, source="threatfox", trigger=trigger)
    run_id = run.id

    inserted = 0
    updated = 0
    skipped = 0
    unmapped = 0
    error_msg: Optional[str] = None
    metadata: dict[str, Any] = {}

    try:
        api_url = url or THREATFOX_API_URL
        _logger.info("ThreatFox: fetching IOCs (days=%d)", days)

        # ThreatFox API: POST with JSON body
        payload = {"query": "get_iocs", "days": str(days)}

        async with aiohttp.ClientSession() as http:
            async with http.post(
                api_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"ThreatFox fetch failed: HTTP {resp.status}")
                data = await resp.json(content_type=None)

        query_status = data.get("query_status", "unknown")
        metadata["query_status"] = query_status

        if query_status != "ok":
            # No results or API error — not necessarily a failure
            if query_status in ("no_result", "empty"):
                _logger.info("ThreatFox: no new IOCs (query_status=%s)", query_status)
                await finish_feed_pull_run(
                    session,
                    run_id=run_id,
                    status="ok",
                    inserted_count=0,
                    updated_count=0,
                    skipped_count=0,
                    unmapped_count=0,
                    metadata_json=metadata,
                )
                return {
                    "run_id": run_id,
                    "source": "threatfox",
                    "status": "ok",
                    "inserted": 0,
                    "updated": 0,
                    "skipped": 0,
                    "unmapped": 0,
                    "error": None,
                    "metadata": metadata,
                }
            raise RuntimeError(f"ThreatFox API error: {query_status}")

        iocs = data.get("data", [])
        metadata["total_iocs"] = len(iocs)
        _logger.info("ThreatFox: %d IOCs returned", len(iocs))

        # Build group lookup maps
        group_by_name = await _build_group_lookup(session)
        malware_to_group = await _build_malware_to_group_lookup(session)

        for ioc_entry in iocs:
            try:
                ioc_id = ioc_entry.get("id", "")
                ioc_value = ioc_entry.get("ioc", "").strip()
                ioc_type = ioc_entry.get("ioc_type", "")
                threat_type = ioc_entry.get("threat_type", "")
                malware_name = ioc_entry.get("malware", "")
                malware_printable = ioc_entry.get("malware_printable", "")
                confidence_level = ioc_entry.get("confidence_level", 50)
                first_seen = ioc_entry.get("first_seen_utc")
                last_seen = ioc_entry.get("last_seen_utc")
                reporter = ioc_entry.get("reporter", "")
                tags = ioc_entry.get("tags", "")

                # Only process IP-type IOCs (ioc_type == "ip:port" or "ip")
                if ioc_type not in ("ip:port", "ip"):
                    skipped += 1
                    continue

                # Extract IP address (strip port if present)
                ip_address = ioc_value.split(":")[0] if ":" in ioc_value else ioc_value
                if not ip_address:
                    skipped += 1
                    continue

                # Map to threat group
                # Strategy: try malware name → group, then try tags → group name
                group_id: Optional[str] = None

                # 1. Try malware name lookup
                if malware_printable:
                    group_id = group_by_name.get(malware_printable.lower())
                if group_id is None and malware_name:
                    group_id = group_by_name.get(malware_name.lower())

                # 2. Try malware → group from existing IPs
                if group_id is None and malware_printable:
                    group_id = malware_to_group.get(malware_printable.lower())
                if group_id is None and malware_name:
                    group_id = malware_to_group.get(malware_name.lower())

                # 3. Try tags (sometimes tags contain group names)
                if group_id is None and tags:
                    for tag in tags.split(","):
                        tag = tag.strip().lower()
                        if tag in group_by_name:
                            group_id = group_by_name[tag]
                            break

                if group_id is None:
                    # Cannot map to any group — increment unmapped, don't create pseudo-group
                    unmapped += 1
                    continue

                # Parse confidence (ThreatFox uses 0-100 scale)
                try:
                    confidence = float(confidence_level) / 100.0
                except (ValueError, TypeError):
                    confidence = 0.5

                # Parse timestamps
                first_seen_dt = _parse_threatfox_ts(first_seen)
                last_seen_dt = _parse_threatfox_ts(last_seen)

                # Determine IP type from threat_type
                ip_type = "c2"
                if "botnet" in threat_type.lower():
                    ip_type = "c2"
                elif "scanner" in threat_type.lower():
                    ip_type = "scanner"

                source_refs = [{
                    "source": "threatfox",
                    "source_id": ioc_id,
                    "url": f"https://threatfox.abuse.ch/ioc/{ioc_id}",
                    "observed_at": last_seen,
                    "confidence": confidence,
                    "metadata": {
                        "malware": malware_printable or malware_name,
                        "reporter": reporter,
                        "tags": tags,
                    },
                }]

                _, created = await upsert_threat_infra_ip(
                    session,
                    group_id=group_id,
                    ip_address=ip_address,
                    ip_type=ip_type,
                    malware_family=malware_printable or malware_name,
                    first_seen=first_seen_dt,
                    last_seen=last_seen_dt,
                    status="active",
                    source="threatfox",
                    confidence=confidence,
                    source_refs=source_refs,
                    tags=tags.split(",") if tags else [],
                )

                if created:
                    inserted += 1
                else:
                    updated += 1

            except Exception as exc:
                _logger.warning("ThreatFox: failed to process IOC %s: %s", ioc_entry.get("id"), exc)
                unmapped += 1

    except Exception as exc:
        error_msg = str(exc)
        _logger.error("ThreatFox pull failed: %s", error_msg)

    status = "ok" if error_msg is None else "failed"
    if error_msg is None and unmapped > 0:
        status = "partial"

    await finish_feed_pull_run(
        session,
        run_id=run_id,
        status=status,
        inserted_count=inserted,
        updated_count=updated,
        skipped_count=skipped,
        unmapped_count=unmapped,
        error_message=error_msg,
        metadata_json=metadata,
    )

    _logger.info(
        "ThreatFox pull: inserted=%d updated=%d skipped=%d unmapped=%d status=%s",
        inserted, updated, skipped, unmapped, status,
    )

    return {
        "run_id": run_id,
        "source": "threatfox",
        "status": status,
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "unmapped": unmapped,
        "error": error_msg,
        "metadata": metadata,
    }


def _parse_threatfox_ts(value: Optional[str]) -> Optional[datetime]:
    """Parse a ThreatFox UTC timestamp string.

    ThreatFox uses formats like ``2026-06-15T14:30:00Z`` or
    ``2026-06-15 14:30:00 UTC``.
    """
    if not value:
        return None
    # Try ISO format with Z
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S UTC",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.strptime(value.strip(), fmt).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
    return None

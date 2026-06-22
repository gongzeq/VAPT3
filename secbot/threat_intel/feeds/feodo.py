"""abuse.ch Feodo Tracker feed puller.

Fetches botnet C2 IP data from Feodo Tracker and upserts as ThreatInfraIP
records.  Feodo tracks specific botnets (Emotet, TrickBot, Dridex, QakBot,
Pikabot).

Group mapping: malware name -> group via existing ThreatMalwareFamily
and ThreatInfraIP records, then via APT alias table.

Data source: https://feodotracker.abuse.ch/downloads/datatable.json
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import aiohttp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from secbot.threat_intel.models import ThreatInfraIP, ThreatMalwareFamily
from secbot.threat_intel.repo import (
    create_feed_pull_run,
    finish_feed_pull_run,
    upsert_threat_infra_ip,
)

_logger = logging.getLogger(__name__)

FEODO_URL = "https://feodotracker.abuse.ch/downloads/datatable.json"


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO datetime string."""
    if not value:
        return None
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.strptime(value.strip(), fmt).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
    return None


async def _build_malware_to_group(session: AsyncSession) -> dict[str, str]:
    """Build lower(malware_family) -> group_id from existing records."""
    lookup: dict[str, str] = {}

    # From ThreatMalwareFamily
    result = await session.execute(
        select(ThreatMalwareFamily.family_name, ThreatMalwareFamily.group_id)
    )
    for row in result:
        if row.family_name:
            lookup[row.family_name.lower()] = row.group_id

    # From ThreatInfraIP
    result = await session.execute(
        select(ThreatInfraIP.malware_family, ThreatInfraIP.group_id)
        .where(ThreatInfraIP.malware_family.isnot(None))
        .distinct()
    )
    for row in result:
        if row.malware_family:
            lookup[row.malware_family.lower()] = row.group_id

    return lookup


async def pull_feodo(
    session: AsyncSession,
    *,
    trigger: str = "manual",
    url: Optional[str] = None,
) -> dict[str, Any]:
    """Pull Feodo Tracker C2 IPs and upsert.

    Returns a summary dict with inserted/updated/skipped/unmapped counts.
    """
    run = await create_feed_pull_run(session, source="feodo", trigger=trigger)
    run_id = run.id

    inserted = 0
    updated = 0
    skipped = 0
    unmapped = 0
    error_msg: Optional[str] = None
    metadata: dict[str, Any] = {}

    try:
        fetch_url = url or FEODO_URL
        _logger.info("Feodo Tracker: fetching from %s", fetch_url)

        async with aiohttp.ClientSession() as http:
            async with http.get(fetch_url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"Feodo fetch failed: HTTP {resp.status}")
                data = await resp.json(content_type=None)

        if not isinstance(data, list):
            raise RuntimeError(f"Feodo: unexpected response type {type(data)}")

        metadata["total_entries"] = len(data)
        _logger.info("Feodo Tracker: %d entries", len(data))

        malware_to_group = await _build_malware_to_group(session)

        for entry in data:
            try:
                ip_address = entry.get("dst_ip", "").strip()
                if not ip_address:
                    skipped += 1
                    continue

                malware = entry.get("malware", "").strip()
                if not malware:
                    skipped += 1
                    continue

                # Map to group
                group_id = malware_to_group.get(malware.lower())
                if group_id is None:
                    unmapped += 1
                    continue

                first_seen = _parse_ts(entry.get("first_seen"))
                last_seen = _parse_ts(entry.get("last_seen"))
                country = entry.get("country")
                network = entry.get("network")

                source_refs = [{
                    "source": "feodo",
                    "source_id": ip_address,
                    "url": entry.get("login_page", f"https://feodotracker.abuse.ch/browse/malware/{malware}/"),
                    "observed_at": entry.get("last_seen"),
                    "confidence": 0.8,
                    "metadata": {
                        "malware": malware,
                        "country": country,
                        "network": network,
                    },
                }]

                _, created = await upsert_threat_infra_ip(
                    session,
                    group_id=group_id,
                    ip_address=ip_address,
                    ip_type="c2",
                    malware_family=malware,
                    geo_country=country,
                    asn=network,
                    first_seen=first_seen,
                    last_seen=last_seen,
                    status="active",
                    source="feodo",
                    confidence=0.8,
                    source_refs=source_refs,
                    tags=[malware.lower()],
                )

                if created:
                    inserted += 1
                else:
                    updated += 1

            except Exception as exc:
                _logger.warning("Feodo: failed to process entry: %s", exc)
                unmapped += 1

    except Exception as exc:
        error_msg = str(exc)
        _logger.error("Feodo pull failed: %s", error_msg)

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
        "Feodo pull: inserted=%d updated=%d skipped=%d unmapped=%d status=%s",
        inserted, updated, skipped, unmapped, status,
    )

    return {
        "run_id": run_id,
        "source": "feodo",
        "status": status,
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "unmapped": unmapped,
        "error": error_msg,
        "metadata": metadata,
    }

"""MITRE ATT&CK Groups importer.

Fetches intrusion-set objects from the MITRE CTI STIX 2.0 repository and
upserts them as ThreatGroup records.

P0 requirement: ≥150 groups with unique ``mitre_id``.

Data source: https://raw.githubusercontent.com/mitre/cti/master/enterprise-attack/enterprise-attack.json
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

import aiohttp
from sqlalchemy.ext.asyncio import AsyncSession

from secbot.threat_intel.repo import (
    create_feed_pull_run,
    finish_feed_pull_run,
    upsert_threat_group,
)

_logger = logging.getLogger(__name__)

MITRE_CTI_URL = (
    "https://raw.githubusercontent.com/mitre/cti/master/"
    "enterprise-attack/enterprise-attack.json"
)


def _parse_stix_date(value: Optional[str]) -> Optional[date]:
    """Parse a STIX date string (YYYY-MM-DD) to a date object."""
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None


def _extract_first_seen(obj: dict[str, Any]) -> Optional[date]:
    """Extract first_seen from STIX intrusion-set created or modified date."""
    for key in ("created", "modified"):
        val = obj.get(key)
        if val:
            return _parse_stix_date(val)
    return None


def _map_intrusion_set(stix_obj: dict[str, Any]) -> dict[str, Any]:
    """Map a STIX intrusion-set object to ThreatGroup upsert kwargs."""
    # MITRE ID is in external_references where source_name == "mitre-attack"
    mitre_id: Optional[str] = None
    for ref in stix_obj.get("external_references", []):
        if ref.get("source_name") == "mitre-attack" and ref.get("external_id"):
            mitre_id = ref["external_id"]
            break

    # Techniques: extract from external_references where source_name == "mitre-attack"
    # and external_id starts with "T"
    # Techniques are usually in a separate relationship, not in the intrusion-set itself

    return {
        "name": stix_obj.get("name", "Unknown"),
        "mitre_id": mitre_id,
        "aliases": stix_obj.get("aliases", []),
        "description": stix_obj.get("description"),
        # Extract first/last seen from STIX metadata
        "first_seen": _extract_first_seen(stix_obj),
        "last_seen": _parse_stix_date(stix_obj.get("modified")),
        "source": "mitre",
        "confidence": 1.0,
        "source_refs": [
            {
                "source": "mitre-attack",
                "source_id": mitre_id,
                "url": f"https://attack.mitre.org/groups/{mitre_id}" if mitre_id else None,
                "observed_at": stix_obj.get("modified"),
                "confidence": 1.0,
            }
        ] if mitre_id else [],
    }


async def import_mitre_groups(
    session: AsyncSession,
    *,
    trigger: str = "manual",
    url: Optional[str] = None,
) -> dict[str, Any]:
    """Import MITRE ATT&CK Groups from the CTI STIX bundle.

    Returns a summary dict with inserted/updated/skipped/unmapped counts.
    """
    run = await create_feed_pull_run(session, source="mitre", trigger=trigger)
    run_id = run.id

    inserted = 0
    updated = 0
    skipped = 0
    unmapped = 0
    error_msg: Optional[str] = None

    try:
        fetch_url = url or MITRE_CTI_URL
        _logger.info("MITRE groups: fetching from %s", fetch_url)

        async with aiohttp.ClientSession() as http:
            async with http.get(fetch_url, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"MITRE CTI fetch failed: HTTP {resp.status}")
                data = await resp.json(content_type=None)

        stix_objects = data.get("objects", [])
        intrusion_sets = [
            obj for obj in stix_objects
            if obj.get("type") == "intrusion-set"
        ]

        _logger.info("MITRE groups: found %d intrusion-set objects", len(intrusion_sets))

        for stix_obj in intrusion_sets:
            try:
                kwargs = _map_intrusion_set(stix_obj)
                if not kwargs["name"] or kwargs["name"] == "Unknown":
                    skipped += 1
                    continue

                _, created = await upsert_threat_group(session, **kwargs)
                if created:
                    inserted += 1
                else:
                    updated += 1
            except Exception as exc:
                _logger.warning("MITRE groups: failed to upsert %s: %s", stix_obj.get("name"), exc)
                unmapped += 1

    except Exception as exc:
        error_msg = str(exc)
        _logger.error("MITRE groups import failed: %s", error_msg)

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
    )

    _logger.info(
        "MITRE groups import: inserted=%d updated=%d skipped=%d unmapped=%d status=%s",
        inserted, updated, skipped, unmapped, status,
    )

    return {
        "run_id": run_id,
        "source": "mitre",
        "status": status,
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "unmapped": unmapped,
        "error": error_msg,
    }

"""CISA KEV (Known Exploited Vulnerabilities) feed puller.

Fetches the CISA KEV catalog JSON and upserts each entry as a ThreatVuln.

P0: every KEV entry is ingested; CVSS may be absent (displayed as "待补充").

Data source: https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json
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
    upsert_threat_vuln,
)

_logger = logging.getLogger(__name__)

CISA_KEV_URL = (
    "https://www.cisa.gov/sites/default/files/feeds/"
    "known_exploited_vulnerabilities.json"
)


def _parse_date(value: Optional[str]) -> Optional[date]:
    """Parse a YYYY-MM-DD string to a date object."""
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


async def pull_cisa_kev(
    session: AsyncSession,
    *,
    trigger: str = "manual",
    url: Optional[str] = None,
) -> dict[str, Any]:
    """Pull CISA KEV catalog and upsert vulnerabilities.

    Returns a summary dict with inserted/updated/skipped/unmapped counts.
    """
    run = await create_feed_pull_run(session, source="cisa_kev", trigger=trigger)
    run_id = run.id

    inserted = 0
    updated = 0
    skipped = 0
    unmapped = 0
    error_msg: Optional[str] = None
    metadata: dict[str, Any] = {}

    try:
        fetch_url = url or CISA_KEV_URL
        _logger.info("CISA KEV: fetching from %s", fetch_url)

        async with aiohttp.ClientSession() as http:
            async with http.get(fetch_url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"CISA KEV fetch failed: HTTP {resp.status}")
                data = await resp.json(content_type=None)

        vulnerabilities = data.get("vulnerabilities", [])
        catalog_version = data.get("catalogVersion")
        metadata["catalog_version"] = catalog_version
        metadata["total_entries"] = len(vulnerabilities)

        _logger.info("CISA KEV: %d entries (catalog version %s)", len(vulnerabilities), catalog_version)

        for vuln_entry in vulnerabilities:
            try:
                cve_id = vuln_entry.get("cveID", "").strip()
                if not cve_id:
                    skipped += 1
                    continue

                date_added = _parse_date(vuln_entry.get("dateAdded"))
                vendor_project = vuln_entry.get("vendorProject", "")
                product = vuln_entry.get("product", "")
                vuln_name = vuln_entry.get("vulnerabilityName", "")
                short_desc = vuln_entry.get("shortDescription", "")
                required_action = vuln_entry.get("requiredAction", "")
                known_ransomware = vuln_entry.get("knownRansomwareCampaignUse", "unknown")

                # Build title from vulnerabilityName or vendor/product
                title = vuln_name or f"{vendor_project} {product} Vulnerability"

                # Build description
                description = short_desc
                if required_action:
                    description = f"{short_desc}\n\nRequired Action: {required_action}"

                # Affected products
                affected_products = []
                if vendor_project and product:
                    affected_products = [f"{vendor_project} {product}"]

                # Source refs
                source_refs = [{
                    "source": "cisa_kev",
                    "source_id": cve_id,
                    "url": "https://www.cisa.gov/known-exploited-vulnerabilities-catalog",
                    "observed_at": vuln_entry.get("dateAdded"),
                    "confidence": 1.0,
                    "metadata": {
                        "vendor": vendor_project,
                        "product": product,
                        "ransomware_use": known_ransomware,
                    },
                }]

                _, created = await upsert_threat_vuln(
                    session,
                    cve_id=cve_id,
                    title=title,
                    description=description,
                    cvss_score=None,  # CISA KEV doesn't include CVSS; NVD supplement in P1
                    severity="high",  # CISA KEV → at least high
                    affected_products=affected_products,
                    is_cisa_kev=True,
                    cisa_kev_date=date_added,
                    published_date=date_added,
                    primary_source="cisa_kev",
                    sources=["cisa_kev"],
                    source_refs=source_refs,
                    tags=[f"ransomware:{known_ransomware}"] if known_ransomware != "unknown" else [],
                )

                if created:
                    inserted += 1
                else:
                    updated += 1

            except Exception as exc:
                _logger.warning("CISA KEV: failed to upsert %s: %s", vuln_entry.get("cveID"), exc)
                unmapped += 1

    except Exception as exc:
        error_msg = str(exc)
        _logger.error("CISA KEV pull failed: %s", error_msg)

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
        "CISA KEV pull: inserted=%d updated=%d skipped=%d unmapped=%d status=%s",
        inserted, updated, skipped, unmapped, status,
    )

    return {
        "run_id": run_id,
        "source": "cisa_kev",
        "status": status,
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "unmapped": unmapped,
        "error": error_msg,
        "metadata": metadata,
    }

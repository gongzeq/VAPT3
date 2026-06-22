"""NVD (National Vulnerability Database) feed puller.

Fetches CVEs with CVSS >= 7.0 from the NVD API and upserts them as
ThreatVuln records.  When a CVE already exists from CISA KEV, NVD data
supplements the record (CVSS, CPE, description) without duplicating.

Rate-limit handling: NVD returns HTTP 404 when rate-limited (not 429).
Without an API key: sleep 6s between paginated requests.
With an API key: sleep 1s between paginated requests.

Data source: https://services.nvd.nist.gov/rest/json/cves/2.0
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import aiohttp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from secbot.threat_intel.models import ThreatVuln
from secbot.threat_intel.repo import (
    create_feed_pull_run,
    finish_feed_pull_run,
    upsert_threat_vuln,
)

_logger = logging.getLogger(__name__)

NVD_API_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"


def _parse_date(value: Optional[str]) -> Optional[date]:
    """Parse an ISO date string to a date object."""
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None


async def _check_supply_chain(
    session: AsyncSession, affected_products: list[str]
) -> tuple[bool, list[str]]:
    """Check if any CPE matches the industry_cpe table.

    Returns (is_supply_chain, matched_cpes).
    """
    from secbot.threat_intel.models import IndustryCPE

    if not affected_products:
        return False, []

    result = await session.execute(select(IndustryCPE.cpe_string))
    industry_cpes = {row.cpe_string for row in result}

    matched: list[str] = []
    for cpe in affected_products:
        # Exact match
        if cpe in industry_cpes:
            matched.append(cpe)
            continue
        # Prefix match (CPE version wildcard — match up to version part)
        cpe_prefix = ":".join(cpe.split(":")[:5])
        for ind_cpe in industry_cpes:
            ind_prefix = ":".join(ind_cpe.split(":")[:5])
            if cpe_prefix == ind_prefix:
                matched.append(cpe)
                break

    return len(matched) > 0, matched


async def pull_nvd(
    session: AsyncSession,
    *,
    trigger: str = "manual",
    url: Optional[str] = None,
    days: int = 1,
) -> dict[str, Any]:
    """Pull NVD CVEs (CVSS >= 7.0) and upsert vulnerabilities.

    Returns a summary dict with inserted/updated/skipped/unmapped counts.
    """
    run = await create_feed_pull_run(session, source="nvd", trigger=trigger)
    run_id = run.id

    inserted = 0
    updated = 0
    skipped = 0
    unmapped = 0
    error_msg: Optional[str] = None
    metadata: dict[str, Any] = {}

    api_key = os.environ.get("NVD_API_KEY", "")
    sleep_seconds = 1.0 if api_key else 6.0

    try:
        api_url = url or NVD_API_URL
        now = datetime.now(timezone.utc)
        start_date = now - timedelta(days=days)
        pub_start = start_date.strftime("%Y-%m-%dT00:00:00.000")

        _logger.info("NVD: fetching CVEs since %s (days=%d)", pub_start, days)

        headers: dict[str, str] = {}
        if api_key:
            headers["apiKey"] = api_key

        all_vulns: list[dict] = []
        start_index = 0
        page_size = 2000

        async with aiohttp.ClientSession() as http:
            while True:
                params = {
                    "pubStartDate": pub_start,
                    "pubEndDate": now.strftime("%Y-%m-%dT23:59:59.999"),
                    "resultsPerPage": str(page_size),
                    "startIndex": str(start_index),
                }

                async with http.get(
                    api_url,
                    params=params,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    if resp.status == 404:
                        body = await resp.text()
                        if "timeout" in body.lower() or "rate" in body.lower():
                            _logger.warning("NVD rate-limited, sleeping %ss", sleep_seconds)
                            await asyncio.sleep(sleep_seconds)
                            continue
                        raise RuntimeError(f"NVD fetch failed: HTTP 404 — {body[:200]}")
                    if resp.status == 429:
                        _logger.warning("NVD rate-limited (429), sleeping %ss", sleep_seconds)
                        await asyncio.sleep(sleep_seconds * 2)
                        continue
                    if resp.status != 200:
                        raise RuntimeError(f"NVD fetch failed: HTTP {resp.status}")

                    data = await resp.json(content_type=None)

                vulns_page = data.get("vulnerabilities", [])
                total_results = data.get("totalResults", 0)
                all_vulns.extend(vulns_page)

                _logger.info(
                    "NVD: page fetched %d vulns (total %d, fetched %d)",
                    len(vulns_page), total_results, len(all_vulns),
                )

                start_index += len(vulns_page)
                if start_index >= total_results or not vulns_page:
                    break

                await asyncio.sleep(sleep_seconds)

        metadata["total_results"] = len(all_vulns)

        for vuln_entry in all_vulns:
            try:
                cve_data = vuln_entry.get("cve", {})
                cve_id = cve_data.get("id", "").strip()
                if not cve_id:
                    skipped += 1
                    continue

                # Extract CVSS
                cvss_score: Optional[float] = None
                cvss_vector: Optional[str] = None
                metrics = cve_data.get("metrics", {})
                for metric_key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
                    if metric_key in metrics and metrics[metric_key]:
                        first = metrics[metric_key][0]
                        cvss_data = first.get("cvssData", {})
                        cvss_score = cvss_data.get("baseScore")
                        cvss_vector = cvss_data.get("vectorString")
                        break

                # Filter: only CVSS >= 7.0
                if cvss_score is not None and cvss_score < 7.0:
                    skipped += 1
                    continue

                # Extract description (English)
                descriptions = cve_data.get("descriptions", [])
                description = ""
                for desc in descriptions:
                    if desc.get("lang") == "en":
                        description = desc.get("value", "")
                        break
                if not description and descriptions:
                    description = descriptions[0].get("value", "")

                # Title: first 200 chars of description, or CVE ID
                title = description[:200] if description else cve_id

                # Extract affected products (CPE)
                affected_products: list[str] = []
                configurations = cve_data.get("configurations", [])
                for config in configurations:
                    for node in config.get("nodes", []):
                        for cpe_match in node.get("cpeMatch", []):
                            criteria = cpe_match.get("criteria", "")
                            if criteria:
                                affected_products.append(criteria)

                # Parse dates
                published = _parse_date(cve_data.get("published"))

                # Check if existing record is CISA KEV
                existing_result = await session.execute(
                    select(ThreatVuln).where(ThreatVuln.cve_id == cve_id)
                )
                existing_vuln = existing_result.scalar_one_or_none()
                is_kev = existing_vuln is not None and existing_vuln.is_cisa_kev

                # Determine severity
                if cvss_score is not None and cvss_score >= 9.0:
                    severity = "critical"
                else:
                    severity = "high"

                # Build source refs
                source_refs = [{
                    "source": "nvd",
                    "source_id": cve_id,
                    "url": f"https://nvd.nist.gov/vuln/detail/{cve_id}",
                    "observed_at": published.isoformat() if published else None,
                    "confidence": 1.0,
                    "metadata": {"cvss_vector": cvss_vector} if cvss_vector else {},
                }]

                # Build sources list
                if existing_vuln and existing_vuln.sources:
                    sources = existing_vuln.sources
                    if "nvd" not in sources:
                        sources = sources + ["nvd"]
                else:
                    sources = ["nvd"]

                # Primary source: keep "cisa_kev" if existing KEV, else "nvd"
                primary_source = "cisa_kev" if is_kev else "nvd"

                # Industry CPE / supply chain check
                is_supply_chain = False
                if affected_products:
                    is_supply, matched_cpes = await _check_supply_chain(session, affected_products)
                    if is_supply:
                        is_supply_chain = True
                        source_refs.append({
                            "source": "industry_cpe_match",
                            "observed_at": datetime.now(timezone.utc).isoformat(),
                            "confidence": 0.9,
                            "metadata": {"matched_cpes": matched_cpes},
                        })

                _, created = await upsert_threat_vuln(
                    session,
                    cve_id=cve_id,
                    title=title,
                    description=description,
                    cvss_score=cvss_score,
                    severity=severity,
                    affected_products=affected_products if affected_products else None,
                    is_supply_chain=is_supply_chain,
                    is_cisa_kev=is_kev,
                    cisa_kev_date=existing_vuln.cisa_kev_date if existing_vuln else None,
                    published_date=published,
                    primary_source=primary_source,
                    sources=sources,
                    source_refs=source_refs,
                )

                if created:
                    inserted += 1
                else:
                    updated += 1

            except Exception as exc:
                _logger.warning("NVD: failed to upsert %s: %s", cve_data.get("id"), exc)
                unmapped += 1

    except Exception as exc:
        error_msg = str(exc)
        _logger.error("NVD pull failed: %s", error_msg)

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
        "NVD pull: inserted=%d updated=%d skipped=%d unmapped=%d status=%s",
        inserted, updated, skipped, unmapped, status,
    )

    return {
        "run_id": run_id,
        "source": "nvd",
        "status": status,
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "unmapped": unmapped,
        "error": error_msg,
        "metadata": metadata,
    }

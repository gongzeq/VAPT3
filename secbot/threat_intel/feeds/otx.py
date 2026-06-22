"""AlienVault OTX feed puller.

Fetches industry-focused pulses (maritime, transport, SCADA, port security)
from the OTX API and extracts indicators mapped to existing threat groups.

OTX provides pulse-level intelligence — the puller extracts:
- IPv4 indicators -> ThreatInfraIP (if adversary maps to group)
- FileHash-SHA256 -> ThreatMalwareFamily.sample_hashes (if adversary maps)
- CVE -> ThreatGroupVulnAssoc (if adversary maps)
- Attack techniques -> ThreatGroup.techniques

Data source: https://otx.alienvault.com/api/v1/pulses/search
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

import aiohttp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from secbot.threat_intel.models import ThreatGroup, ThreatVuln
from secbot.threat_intel.repo import (
    create_feed_pull_run,
    finish_feed_pull_run,
    upsert_threat_infra_ip,
)

_logger = logging.getLogger(__name__)

OTX_API_URL = "https://otx.alienvault.com/api/v1/pulses/search"

_INDUSTRY_QUERIES = ["maritime", "transport", "scada", "port security"]


async def _build_group_lookup(session: AsyncSession) -> dict[str, str]:
    """Build lower(name) -> group_id and alias -> group_id."""
    result = await session.execute(
        select(ThreatGroup.id, ThreatGroup.name, ThreatGroup.aliases)
    )
    lookup: dict[str, str] = {}
    for row in result:
        lookup[row.name.lower()] = row.id
        if row.aliases:
            for alias in row.aliases:
                if isinstance(alias, str):
                    lookup[alias.lower()] = row.id
    # Also check AptAlias table
    from secbot.threat_intel.models import AptAlias

    result = await session.execute(
        select(AptAlias.alias_name, AptAlias.group_id)
    )
    for row in result:
        if row.alias_name and row.group_id:
            lookup[row.alias_name.lower()] = row.group_id
    return lookup


async def pull_otx(
    session: AsyncSession,
    *,
    trigger: str = "manual",
    url: Optional[str] = None,
    queries: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Pull OTX industry pulses and extract indicators.

    Returns a summary dict with inserted/updated/skipped/unmapped counts.
    """
    run = await create_feed_pull_run(session, source="otx", trigger=trigger)
    run_id = run.id

    inserted = 0
    updated = 0
    skipped = 0
    unmapped = 0
    error_msg: Optional[str] = None
    metadata: dict[str, Any] = {}

    api_key = os.environ.get("OTX_API_KEY", "")
    search_queries = queries or _INDUSTRY_QUERIES
    metadata["queries"] = search_queries

    try:
        api_url = url or OTX_API_URL
        headers: dict[str, str] = {}
        if api_key:
            headers["X-OTX-API-KEY"] = api_key

        group_by_name = await _build_group_lookup(session)

        all_pulses: list[dict] = []

        async with aiohttp.ClientSession() as http:
            for query in search_queries:
                params = {"q": query, "limit": "50", "page": "1"}
                try:
                    async with http.get(
                        api_url,
                        params=params,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=30),
                    ) as resp:
                        if resp.status == 403:
                            raise RuntimeError("OTX auth failed (403) — check OTX_API_KEY")
                        if resp.status != 200:
                            _logger.warning("OTX query '%s' returned HTTP %d", query, resp.status)
                            continue
                        data = await resp.json(content_type=None)

                    pulses = data.get("results", [])
                    all_pulses.extend(pulses)
                    _logger.info("OTX query '%s': %d pulses", query, len(pulses))

                except aiohttp.ClientError as exc:
                    _logger.warning("OTX query '%s' failed: %s", query, exc)
                    continue

                await asyncio.sleep(0.2)  # Courtesy delay

        metadata["total_pulses"] = len(all_pulses)

        # Deduplicate pulses by ID
        seen_pulse_ids: set[str] = set()
        unique_pulses: list[dict] = []
        for pulse in all_pulses:
            pid = pulse.get("id", "")
            if pid and pid not in seen_pulse_ids:
                seen_pulse_ids.add(pid)
                unique_pulses.append(pulse)

        metadata["unique_pulses"] = len(unique_pulses)

        for pulse in unique_pulses:
            try:
                adversary = pulse.get("adversary", "").strip()
                pulse_tags = pulse.get("tags", [])

                # Map adversary to group
                group_id: Optional[str] = None
                if adversary:
                    group_id = group_by_name.get(adversary.lower())

                # If no adversary, try tags for group names
                if group_id is None and pulse_tags:
                    for tag in pulse_tags:
                        if isinstance(tag, str):
                            gid = group_by_name.get(tag.lower())
                            if gid:
                                group_id = gid
                                break

                if group_id is None:
                    unmapped += 1
                    continue

                # Extract indicators
                indicators = pulse.get("indicators", [])
                pulse_url = f"https://otx.alienvault.com/pulse/{pulse.get('id', '')}"
                pulse_created = pulse.get("created", "")

                for indicator in indicators:
                    try:
                        ind_type = indicator.get("type", "")
                        ind_value = indicator.get("indicator", "").strip()
                        ind_title = indicator.get("title", "")

                        if not ind_value:
                            continue

                        source_refs = [{
                            "source": "otx",
                            "source_id": pulse.get("id", ""),
                            "url": pulse_url,
                            "observed_at": pulse_created,
                            "confidence": 0.7,
                            "metadata": {
                                "pulse_name": pulse.get("name", ""),
                                "indicator_title": ind_title,
                            },
                        }]

                        if ind_type == "IPv4":
                            # Extract IP (strip port/CIDR)
                            ip = ind_value.split("/")[0].split(":")[0]
                            _, created = await upsert_threat_infra_ip(
                                session,
                                group_id=group_id,
                                ip_address=ip,
                                ip_type="c2",
                                malware_family=ind_title if ind_title else None,
                                status="active",
                                source="otx",
                                confidence=0.7,
                                source_refs=source_refs,
                                tags=pulse_tags if pulse_tags else [],
                            )
                            if created:
                                inserted += 1
                            else:
                                updated += 1

                        elif ind_type == "FileHash-SHA256":
                            # Append to existing malware family or create new
                            # Try to find existing family for this group
                            from secbot.threat_intel.models import ThreatMalwareFamily

                            fam_result = await session.execute(
                                select(ThreatMalwareFamily)
                                .where(ThreatMalwareFamily.group_id == group_id)
                                .limit(1)
                            )
                            family = fam_result.scalar_one_or_none()

                            if family:
                                # Append hash to existing family
                                existing_hashes = family.sample_hashes or []
                                existing_hashes.append({
                                    "sha256": ind_value,
                                    "source": "otx",
                                })
                                family.sample_hashes = existing_hashes
                                family.last_ingested_at = datetime.now(timezone.utc)
                                updated += 1
                            else:
                                # Skip — no family to map to
                                skipped += 1

                        elif ind_type == "CVE":
                            # Check if CVE exists in ThreatVuln
                            cve_result = await session.execute(
                                select(ThreatVuln).where(ThreatVuln.cve_id == ind_value)
                            )
                            existing_vuln = cve_result.scalar_one_or_none()
                            if existing_vuln:
                                # Create association
                                from secbot.threat_intel.models import ThreatGroupVulnAssoc
                                from secbot.threat_intel.repo import generate_ulid

                                assoc_result = await session.execute(
                                    select(ThreatGroupVulnAssoc).where(
                                        ThreatGroupVulnAssoc.group_id == group_id,
                                        ThreatGroupVulnAssoc.vulnerability_id == existing_vuln.id,
                                    )
                                )
                                existing_assoc = assoc_result.scalar_one_or_none()
                                if existing_assoc is None:
                                    assoc = ThreatGroupVulnAssoc(
                                        id=generate_ulid(),
                                        group_id=group_id,
                                        vulnerability_id=existing_vuln.id,
                                        relationship_type="reported",
                                        confidence=0.7,
                                        source_refs=source_refs,
                                    )
                                    session.add(assoc)
                                    await session.flush()
                                    inserted += 1
                                else:
                                    updated += 1
                            else:
                                skipped += 1

                        else:
                            skipped += 1

                    except Exception as exc:
                        _logger.warning("OTX: failed to process indicator: %s", exc)
                        unmapped += 1

            except Exception as exc:
                _logger.warning("OTX: failed to process pulse: %s", exc)
                unmapped += 1

    except Exception as exc:
        error_msg = str(exc)
        _logger.error("OTX pull failed: %s", error_msg)

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
        "OTX pull: inserted=%d updated=%d skipped=%d unmapped=%d status=%s",
        inserted, updated, skipped, unmapped, status,
    )

    return {
        "run_id": run_id,
        "source": "otx",
        "status": status,
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "unmapped": unmapped,
        "error": error_msg,
        "metadata": metadata,
    }

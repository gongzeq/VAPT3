"""Industry CPE matching and seed data.

Provides ``check_supply_chain()`` to determine if a vulnerability's
affected products match industry CPE entries (maritime/transport/SCADA).

Also provides ``seed_industry_cpes()`` to populate the industry_cpe
table with initial maritime/transport product entries.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from secbot.threat_intel.models import IndustryCPE

_logger = logging.getLogger(__name__)

# Seed data: maritime / transport / SCADA products
_SEED_CPES: list[dict[str, str]] = [
    {"cpe_string": "cpe:2.3:a:siemens:simatic", "product_name": "Siemens SIMATIC SCADA", "vendor": "Siemens", "industry_tag": "maritime/scada"},
    {"cpe_string": "cpe:2.3:a:schneider:modicon", "product_name": "Schneider Modicon PLC", "vendor": "Schneider Electric", "industry_tag": "maritime/scada"},
    {"cpe_string": "cpe:2.3:a:aveva:intouch", "product_name": "AVEVA InTouch HMI", "vendor": "AVEVA", "industry_tag": "maritime/scada"},
    {"cpe_string": "cpe:2.3:h:kongsberg:k-ship", "product_name": "Kongsberg K-Ship", "vendor": "Kongsberg", "industry_tag": "maritime"},
    {"cpe_string": "cpe:2.3:a:wondershare:", "product_name": "Wondershare (fleet mgmt)", "vendor": "Wondershare", "industry_tag": "transport"},
    {"cpe_string": "cpe:2.3:a:rockwell:factorytalk", "product_name": "Rockwell FactoryTalk", "vendor": "Rockwell Automation", "industry_tag": "scada"},
    {"cpe_string": "cpe:2.3:a:mitsubishi:mitsubishi_mc_protocol", "product_name": "Mitsubishi MC Protocol", "vendor": "Mitsubishi", "industry_tag": "scada"},
    {"cpe_string": "cpe:2.3:a:abb:freelance", "product_name": "ABB Freelance DCS", "vendor": "ABB", "industry_tag": "scada"},
    {"cpe_string": "cpe:2.3:a:garmin:garmin_nav", "product_name": "Garmin Navigation", "vendor": "Garmin", "industry_tag": "maritime"},
    {"cpe_string": "cpe:2.3:a:furuno:ecdis", "product_name": "Furuno ECDIS", "vendor": "Furuno", "industry_tag": "maritime"},
]


async def check_supply_chain(
    session: AsyncSession, affected_products: list[str]
) -> tuple[bool, list[str]]:
    """Check if any CPE in affected_products matches industry_cpe table.

    Returns (is_supply_chain, matched_cpes).
    """
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
        cpe_parts = cpe.split(":")
        cpe_prefix = ":".join(cpe_parts[:5]) if len(cpe_parts) >= 5 else cpe
        for ind_cpe in industry_cpes:
            ind_parts = ind_cpe.split(":")
            ind_prefix = ":".join(ind_parts[:5]) if len(ind_parts) >= 5 else ind_cpe
            if cpe_prefix == ind_prefix or cpe.startswith(ind_cpe):
                matched.append(cpe)
                break

    return len(matched) > 0, matched


async def seed_industry_cpes(session: AsyncSession) -> dict[str, int]:
    """Seed the industry_cpe table with maritime/transport products.

    Returns {"inserted": N, "skipped": M}.
    """
    inserted = 0
    skipped = 0

    # Get existing CPE strings
    result = await session.execute(select(IndustryCPE.cpe_string))
    existing = {row.cpe_string for row in result}

    for entry in _SEED_CPES:
        if entry["cpe_string"] in existing:
            skipped += 1
            continue
        cpe = IndustryCPE(
            cpe_string=entry["cpe_string"],
            product_name=entry["product_name"],
            vendor=entry.get("vendor"),
            industry_tag=entry.get("industry_tag", "maritime"),
            confidence=0.9,
            source="seed",
        )
        session.add(cpe)
        inserted += 1

    if inserted > 0:
        await session.flush()

    _logger.info("Industry CPE seed: inserted=%d skipped=%d", inserted, skipped)
    return {"inserted": inserted, "skipped": skipped}

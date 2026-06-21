"""Chinese APT alias seed data.

Maps Chinese naming conventions (奇安信/安恒/360 etc.) to MITRE ATT&CK
group IDs.  This enables searching for "海莲花" and finding APT-C-00 /
OceanLotus / Group-G0040.

P0 requirement: ≥20 aliases covering the most common Chinese APT names.

Sources: public annual threat reports from Qihoo 360, Anheng, QiAnXin,
and curated community mappings.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from secbot.threat_intel.repo import upsert_apt_alias

_logger = logging.getLogger(__name__)

# ── Seed data ────────────────────────────────────────────────────────────
# Each entry: (alias_name, mitre_id_or_name, naming_org, confidence, source_url)
# mitre_id is used to look up the group after MITRE import; if the MITRE ID
# is unknown, we store the alias with group_id=None and it can be matched
# later by name.

APT_ALIASES_SEED: list[dict[str, Any]] = [
    # 海莲花 (APT-C-00 / OceanLotus / APT32)
    {"alias_name": "海莲花", "mitre_id": "G0040", "naming_org": "奇安信", "confidence": 0.95},
    {"alias_name": "APT-C-00", "mitre_id": "G0040", "naming_org": "360", "confidence": 0.95},
    {"alias_name": "OceanLotus", "mitre_id": "G0040", "naming_org": "Mandiant", "confidence": 0.95},

    # 蔓灵花 (APT-C-08 / Kimsuky / Velvet Chollima)
    {"alias_name": "蔓灵花", "mitre_id": "G0094", "naming_org": "奇安信", "confidence": 0.9},
    {"alias_name": "APT-C-08", "mitre_id": "G0094", "naming_org": "360", "confidence": 0.9},

    # 毒云藤 (APT-C-02 / Patchwork / Dropping Elephant)
    {"alias_name": "毒云藤", "mitre_id": "G0040", "naming_org": "奇安信", "confidence": 0.8},
    {"alias_name": "APT-C-02", "mitre_id": "G0040", "naming_org": "360", "confidence": 0.8},

    # 摩诃草 (APT-C-01 / Patchwork / MONSOON)
    {"alias_name": "摩诃草", "mitre_id": "G0126", "naming_org": "奇安信", "confidence": 0.85},
    {"alias_name": "APT-C-01", "mitre_id": "G0126", "naming_org": "360", "confidence": 0.85},

    # 黄金鼠 (APT-C-27 / Arid Viper)
    {"alias_name": "黄金鼠", "mitre_id": None, "naming_org": "360", "confidence": 0.8},
    {"alias_name": "APT-C-27", "mitre_id": None, "naming_org": "360", "confidence": 0.8},

    # 蓝宝菇 (APT-C-12 / APT-C-12)
    {"alias_name": "蓝宝菇", "mitre_id": None, "naming_org": "奇安信", "confidence": 0.8},
    {"alias_name": "APT-C-12", "mitre_id": None, "naming_org": "360", "confidence": 0.8},

    # 猪肝菜 (APT-C-09 / APT-C-09)
    {"alias_name": "猪肝菜", "mitre_id": None, "naming_org": "360", "confidence": 0.75},
    {"alias_name": "APT-C-09", "mitre_id": None, "naming_org": "360", "confidence": 0.75},

    # 肚脑虫 (APT-C-35 / Donot Team)
    {"alias_name": "肚脑虫", "mitre_id": None, "naming_org": "奇安信", "confidence": 0.8},
    {"alias_name": "APT-C-35", "mitre_id": None, "naming_org": "360", "confidence": 0.8},

    # 盲眼鹰 (APT-C-23 / Blind Eagle)
    {"alias_name": "盲眼鹰", "mitre_id": None, "naming_org": "奇安信", "confidence": 0.75},
    {"alias_name": "APT-C-23", "mitre_id": None, "naming_org": "360", "confidence": 0.75},

    # 猞猁 (APT-C-30 / Lynx)
    {"alias_name": "猞猁", "mitre_id": None, "naming_org": "360", "confidence": 0.7},
    {"alias_name": "APT-C-30", "mitre_id": None, "naming_org": "360", "confidence": 0.7},

    # APT41 / Winnti / Barium / Double Dragon
    {"alias_name": "APT41", "mitre_id": "G0096", "naming_org": "FireEye", "confidence": 0.95},
    {"alias_name": "Winnti", "mitre_id": "G0044", "naming_org": "Kaspersky", "confidence": 0.85},
    {"alias_name": "Barium", "mitre_id": "G0126", "naming_org": "Microsoft", "confidence": 0.8},

    # 拉撒路 (Lazarus Group / Hidden Cobra)
    {"alias_name": "拉撒路", "mitre_id": "G0032", "naming_org": "中文社区", "confidence": 0.95},
    {"alias_name": "Hidden Cobra", "mitre_id": "G0032", "naming_org": "US-CERT", "confidence": 0.95},

    # 沙虫 (Sandworm / Voodoo Bear / IRIDIUM)
    {"alias_name": "沙虫", "mitre_id": "G0034", "naming_org": "中文社区", "confidence": 0.9},
    {"alias_name": "Voodoo Bear", "mitre_id": "G0034", "naming_org": "CrowdStrike", "confidence": 0.9},
]


async def seed_apt_aliases(session: AsyncSession) -> int:
    """Seed the APT alias table with Chinese / vendor naming mappings.

    Returns the number of aliases seeded (new + updated).
    """
    # Build a lookup of mitre_id → group_id from existing groups
    from sqlalchemy import select

    from secbot.threat_intel.models import ThreatGroup

    result = await session.execute(
        select(ThreatGroup.id, ThreatGroup.mitre_id)
    )
    mitre_to_group: dict[str, str] = {}
    for row in result:
        if row.mitre_id:
            mitre_to_group[row.mitre_id] = row.id

    count = 0
    for entry in APT_ALIASES_SEED:
        mitre_id = entry.get("mitre_id")
        group_id = mitre_to_group.get(mitre_id) if mitre_id else None

        await upsert_apt_alias(
            session,
            alias_name=entry["alias_name"],
            group_id=group_id,
            naming_org=entry.get("naming_org"),
            confidence=entry.get("confidence", 0.8),
            source_url=entry.get("source_url"),
        )
        count += 1

    _logger.info("APT aliases seed: %d entries processed", count)
    return count

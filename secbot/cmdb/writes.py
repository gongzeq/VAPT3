"""Apply skill-generated ``cmdb_writes`` to the CMDB.

This module bridges the declarative write instructions produced by skill
handlers and the imperative repository helpers in :mod:`secbot.cmdb.repo`.
"""

from __future__ import annotations

import ipaddress
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from secbot.cmdb.models import DEFAULT_ACTOR
from secbot.cmdb.repo import (
    upsert_asset,
    upsert_service,
    upsert_vulnerability,
)

_logger = logging.getLogger(__name__)


def _is_ip(target: str) -> bool:
    """Return ``True`` when *target* looks like an IPv4/IPv6 address."""
    try:
        ipaddress.ip_address(target)
        return True
    except ValueError:
        return False


async def apply_cmdb_writes(
    session: AsyncSession,
    actor_id: str,
    scan_id: str,
    writes: list[dict[str, Any]],
    *,
    discovered_by: str = "skill",
) -> None:
    """Execute a batch of skill-generated CMDB write instructions.

    Each write is a dict with keys ``table``, ``op``, and ``data``.
    Supported combinations:

    - ``table="assets"``, ``op="upsert"`` → :func:`upsert_asset`
    - ``table="services"``, ``op="upsert"`` → :func:`upsert_service`
    - ``table="vulnerabilities"``, ``op="upsert"`` → :func:`upsert_vulnerability`

    Assets are looked up or created lazily and cached per *target* so that a
    single skill turn that writes both services and vulnerabilities for the
    same host only touches the ``asset`` table once.
    """
    target_to_asset: dict[str, Any] = {}

    for write in writes:
        table = write.get("table")
        op = write.get("op")
        data = write.get("data", {})

        if op != "upsert":
            _logger.warning("Unsupported cmdb op %r for table %r", op, table)
            continue

        if table == "assets":
            target = data.get("target", scan_id)
            if target not in target_to_asset:
                asset = await upsert_asset(
                    session,
                    actor_id or DEFAULT_ACTOR,
                    scan_id=scan_id,
                    target=target,
                    ip=data.get("ip") if _is_ip(data.get("ip", "")) else None,
                    hostname=data.get("hostname") if not _is_ip(data.get("target", "")) else None,
                    os_guess=data.get("os_guess"),
                    tags=data.get("tags"),
                )
                target_to_asset[target] = asset

        elif table == "services":
            target = data.get("target", scan_id)
            if target not in target_to_asset:
                asset = await upsert_asset(
                    session,
                    actor_id or DEFAULT_ACTOR,
                    scan_id=scan_id,
                    target=target,
                    ip=target if _is_ip(target) else None,
                    hostname=target if not _is_ip(target) else None,
                )
                target_to_asset[target] = asset
            asset = target_to_asset[target]
            await upsert_service(
                session,
                actor_id or DEFAULT_ACTOR,
                asset_id=asset.id,
                port=int(data["port"]),
                protocol=data.get("protocol", "tcp"),
                state=data.get("state", "open"),
                service=data.get("service") or None,
                product=data.get("product") or None,
                version=data.get("version") or None,
            )

        elif table == "vulnerabilities":
            target = data.get("target", scan_id)
            if target not in target_to_asset:
                asset = await upsert_asset(
                    session,
                    actor_id or DEFAULT_ACTOR,
                    scan_id=scan_id,
                    target=target,
                    ip=target if _is_ip(target) else None,
                    hostname=target if not _is_ip(target) else None,
                )
                target_to_asset[target] = asset
            asset = target_to_asset[target]
            evidence = data.get("evidence")
            await upsert_vulnerability(
                session,
                actor_id or DEFAULT_ACTOR,
                asset_id=asset.id,
                severity=data.get("severity", "info"),
                category=data.get("category", "other"),
                title=data.get("title", "unknown"),
                discovered_by=discovered_by,
                service_id=None,
                cve_id=data.get("cve_id") or None,
                evidence={"raw": evidence} if evidence else None,
                raw_log_path=data.get("raw_log_path") or None,
            )

        else:
            _logger.warning("Unsupported cmdb table %r", table)

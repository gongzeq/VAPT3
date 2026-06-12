"""Apply skill-generated ``cmdb_writes`` to the CMDB.

This module bridges the declarative write instructions produced by skill
handlers and the imperative repository helpers in :mod:`secbot.cmdb.repo`.
"""

from __future__ import annotations

import ipaddress
import logging
import re
from typing import Any, Optional
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from secbot.cmdb.models import DEFAULT_ACTOR
from secbot.cmdb.repo import (
    upsert_asset,
    upsert_service,
    upsert_vulnerability,
)

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Auto-classification: infer ``tags.type`` from asset attributes.
# ---------------------------------------------------------------------------

# RFC-1918 + loopback ranges considered "internal network".
_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local
]

# Well-known middleware product fingerprints (case-insensitive substrings).
_MIDDLEWARE_KEYWORDS = (
    "tomcat", "nginx", "apache", "jetty", "weblogic", "websphere",
    "jboss", "wildfly", "glassfish", "undertow",
    "redis", "memcached", "rabbitmq", "kafka", "activemq", "pulsar",
    "elasticsearch", "solr", "zookeeper", "consul", "nacos", "eureka",
    "mysql", "postgres", "mssql", "oracle", "mongodb", "cassandra",
    "minio", "harbor",
)

# OA / office-automation service fingerprints.
_OA_KEYWORDS = (
    "mail", "smtp", "imap", "pop3", "exchange", "dovecot", "postfix",
    "ldap", "ad", "sso", "cas", "oauth", "oidc",
    "confluence", "jira", "gitlab", "jenkins", "wiki",
    "nextcloud", "owncloud", "roundcube", "zimbra",
)

# Infrastructure / support service fingerprints.
_SUPPORT_KEYWORDS = (
    "dns", "dhcp", "ntp", "snmp", "syslog", "radius",
    "prometheus", "grafana", "zabbix", "nagios", "icinga",
    "ansible", "puppet", "chef", "saltstack",
    "ftp", "tftp", "nfs", "samba", "cifs",
)

# AI / agent endpoint keywords.
_AGENT_KEYWORDS = (
    "agent", "bot", "crawler", "spider", "scraper",
    "llm", "chatbot", "ai", "ml", "model",
)

# HTTP ports that suggest a web-facing business application.
_WEB_PORTS = {80, 443, 8080, 8443, 8000, 8888, 3000, 4200, 5000, 9090}


def _is_private_ip(raw: str) -> bool:
    """Return True if *raw* is a private / loopback IP address."""
    try:
        addr = ipaddress.ip_address(raw)
    except ValueError:
        return False
    return any(addr in net for net in _PRIVATE_NETWORKS)


# Keywords short enough to need word-boundary matching (avoid "ai" matching
# inside "mail", "detail", etc.).
_BOUNDARY_REQUIRED = frozenset({"ai", "ml", "ad"})


def _has_keyword(value: Optional[str], keywords: tuple[str, ...]) -> bool:
    """Case-insensitive keyword match with word-boundary protection for short terms."""
    if not value:
        return False
    v = value.lower()
    for kw in keywords:
        if kw in _BOUNDARY_REQUIRED:
            # Require a word-boundary match for very short keywords.
            if re.search(rf"(?<![a-z]){re.escape(kw)}(?![a-z])", v):
                return True
        elif kw in v:
            return True
    return False


def classify_asset(
    *,
    target: str,
    ip: Optional[str] = None,
    hostname: Optional[str] = None,
    os_guess: Optional[str] = None,
    tags: Optional[dict[str, Any]] = None,
    service_port: Optional[int] = None,
    service_name: Optional[str] = None,
    product: Optional[str] = None,
) -> str:
    """Infer the best ``tags.type`` for an asset.

    Classification priority (highest first):

    1. Explicit ``tags["type"]`` already set by the caller — respected as-is.
    2. AI agent / bot endpoint → ``智能体``
    3. Middleware product detected → ``中间件``
    4. OA / office service detected → ``OA``
    5. Infrastructure service detected → ``支撑``
    6. HTTP(s) URL on a web port → ``业务``
    7. Private / internal IP → ``内网``
    8. Fallback → ``其他``
    """

    # 0 — honour an explicit caller-supplied type.
    if tags and tags.get("type"):
        from secbot.cmdb.models import VALID_ASSET_TYPES
        if tags["type"] in VALID_ASSET_TYPES:
            return tags["type"]

    # Normalise inputs.
    target_lower = (target or "").lower()
    combined = " ".join(filter(None, [target_lower, ip or "", hostname or "",
                                       service_name or "", product or ""])).lower()

    # 1 — AI agent / bot.
    if _has_keyword(combined, _AGENT_KEYWORDS):
        return "智能体"

    # 2 — Middleware.
    if _has_keyword(combined, _MIDDLEWARE_KEYWORDS):
        return "中间件"

    # 3 — OA.
    if _has_keyword(combined, _OA_KEYWORDS):
        return "OA"

    # 4 — Infrastructure / support.
    if _has_keyword(combined, _SUPPORT_KEYWORDS):
        return "支撑"

    # 5 — HTTP(S) URL on a web port → business application.
    if re.match(r"^https?://", target_lower):
        try:
            parsed = urlparse(target_lower)
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            if port in _WEB_PORTS:
                return "业务"
        except Exception:
            pass
        # Any HTTP URL is still likely a business app.
        return "业务"

    # 6 — Private IP → internal network.
    effective_ip = ip or target
    if effective_ip and _is_private_ip(effective_ip):
        return "内网"

    # 7 — Port-based inference for non-URL targets.
    if service_port:
        if service_port in _WEB_PORTS:
            return "业务"
        if service_port in {22, 3389, 5900}:
            return "内网"

    return "其他"


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

    def _ensure_typed_tags(
        target: str,
        ip: Optional[str],
        hostname: Optional[str],
        os_guess: Optional[str],
        raw_tags: Optional[dict[str, Any]],
        service_port: Optional[int] = None,
        service_name: Optional[str] = None,
        product: Optional[str] = None,
    ) -> dict[str, Any]:
        """Return *tags* dict with ``type`` auto-filled when missing."""
        merged = dict(raw_tags) if raw_tags else {}
        inferred = classify_asset(
            target=target,
            ip=ip,
            hostname=hostname,
            os_guess=os_guess,
            tags=merged,
            service_port=service_port,
            service_name=service_name,
            product=product,
        )
        merged["type"] = inferred
        return merged

    for write in writes:
        table = write.get("table")
        op = write.get("op")
        data = write.get("data", {})

        if op != "upsert":
            _logger.warning("Unsupported cmdb op %r for table %r", op, table)
            continue

        if table == "assets":
            target = data.get("target", scan_id)
            raw_ip = data.get("ip", "")
            ip_val = raw_ip if _is_ip(raw_ip) else None
            host_val = data.get("hostname") if not _is_ip(data.get("target", "")) else None
            if target not in target_to_asset:
                asset = await upsert_asset(
                    session,
                    actor_id or DEFAULT_ACTOR,
                    scan_id=scan_id,
                    target=target,
                    ip=ip_val,
                    hostname=host_val,
                    os_guess=data.get("os_guess"),
                    tags=_ensure_typed_tags(
                        target, ip_val, host_val,
                        data.get("os_guess"), data.get("tags"),
                    ),
                )
                target_to_asset[target] = asset

        elif table == "services":
            target = data.get("target", scan_id)
            if target not in target_to_asset:
                svc_ip = target if _is_ip(target) else None
                svc_host = target if not _is_ip(target) else None
                asset = await upsert_asset(
                    session,
                    actor_id or DEFAULT_ACTOR,
                    scan_id=scan_id,
                    target=target,
                    ip=svc_ip,
                    hostname=svc_host,
                    tags=_ensure_typed_tags(
                        target, svc_ip, svc_host, None, None,
                        service_port=int(data.get("port", 0)) or None,
                        service_name=data.get("service"),
                        product=data.get("product"),
                    ),
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
                vuln_ip = target if _is_ip(target) else None
                vuln_host = target if not _is_ip(target) else None
                asset = await upsert_asset(
                    session,
                    actor_id or DEFAULT_ACTOR,
                    scan_id=scan_id,
                    target=target,
                    ip=vuln_ip,
                    hostname=vuln_host,
                    tags=_ensure_typed_tags(
                        target, vuln_ip, vuln_host, None, None,
                    ),
                )
                target_to_asset[target] = asset
            asset = target_to_asset[target]
            evidence = data.get("evidence")
            # Preserve structured evidence dicts as-is; wrap legacy strings.
            if isinstance(evidence, dict):
                evidence_payload = evidence
            elif evidence:
                evidence_payload = {"raw": evidence, "description": str(evidence)}
            else:
                evidence_payload = None
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
                evidence=evidence_payload,
                raw_log_path=data.get("raw_log_path") or None,
            )

        else:
            _logger.warning("Unsupported cmdb table %r", table)

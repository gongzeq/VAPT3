"""REST handlers for the Threat Intel module.

All paths are rooted at ``/api/threat-intel/`` and follow the PRD §6
contract.  Handlers are thin translation shells — business logic stays
in :mod:`secbot.threat_intel.repo` and :mod:`secbot.threat_intel.feeds`.

Error format matches the rest of the API:
``{"error": {"code": "<prefix.detail>", "message": "<human>"}}``
"""

from __future__ import annotations

import logging
from datetime import datetime

from aiohttp import web
from sqlalchemy import select

from secbot.threat_intel import DEFAULT_ACTOR
from secbot.threat_intel.db import get_session
from secbot.threat_intel.models import IndustryCPE
from secbot.threat_intel.repo import (
    add_to_watchlist,
    get_overview,
    get_threat_group,
    list_feed_pull_runs,
    list_maritime_events,
    list_threat_groups,
    list_threat_infra_ips,
    list_threat_malware,
    list_threat_vulns,
    remove_from_watchlist,
    upsert_apt_alias,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _error(status: int, code: str, message: str) -> web.Response:
    return web.json_response(
        {"error": {"code": code, "message": message}}, status=status
    )


def _query_param(request: web.Request, name: str, default: str | None = None) -> str | None:
    return request.query.get(name, default)


def _int_param(request: web.Request, name: str, default: int) -> int:
    try:
        return int(request.query.get(name, default))
    except (ValueError, TypeError):
        return default


def _bool_param(request: web.Request, name: str) -> bool | None:
    val = request.query.get(name)
    if val is None:
        return None
    return val.lower() in ("true", "1", "yes")


async def _ensure_engine() -> None:
    """Lazily init the threat intel engine on first request.

    Uses :func:`get_engine` so the engine is only created once —
    calling ``init_engine`` directly would dispose and recreate the
    engine on every request, losing in-memory data in tests and
    adding unnecessary overhead in production.
    """
    from secbot.threat_intel.db import get_engine
    get_engine()


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

async def handle_overview(request: web.Request) -> web.Response:
    """GET /api/threat-intel/overview — dashboard statistics."""
    await _ensure_engine()
    async with get_session() as session:
        data = await get_overview(session, actor_id=DEFAULT_ACTOR)
    return web.json_response(data)


# ---------------------------------------------------------------------------
# Threat Groups
# ---------------------------------------------------------------------------

async def handle_list_groups(request: web.Request) -> web.Response:
    """GET /api/threat-intel/groups — paginated list with search and filters."""
    await _ensure_engine()
    q = _query_param(request, "q")
    watched = _bool_param(request, "watched")
    origin_country = _query_param(request, "origin_country")
    target_sector = _query_param(request, "target_sector")
    page = _int_param(request, "page", 1)
    page_size = _int_param(request, "page_size", 20)

    async with get_session() as session:
        result = await list_threat_groups(
            session,
            q=q,
            watched_only=bool(watched) if watched is not None else False,
            actor_id=DEFAULT_ACTOR,
            origin_country=origin_country,
            target_sector=target_sector,
            page=page,
            page_size=page_size,
        )
    return web.json_response(result)


async def handle_get_group(request: web.Request) -> web.Response:
    """GET /api/threat-intel/groups/{id} — group detail with relations."""
    await _ensure_engine()
    group_id = request.match_info["id"]
    async with get_session() as session:
        data = await get_threat_group(session, group_id, actor_id=DEFAULT_ACTOR)
    if data is None:
        return _error(404, "not_found", f"Threat group {group_id} not found")
    return web.json_response(data)


async def handle_watch_group(request: web.Request) -> web.Response:
    """POST /api/threat-intel/groups/{id}/watch — add to watchlist."""
    await _ensure_engine()
    group_id = request.match_info["id"]
    note = None
    try:
        body = await request.json()
        note = body.get("note")
    except Exception:
        pass  # Body is optional

    async with get_session() as session:
        entry = await add_to_watchlist(
            session, group_id=group_id, actor_id=DEFAULT_ACTOR, note=note
        )
    return web.json_response({
        "group_id": group_id,
        "watched": True,
        "note": entry.note,
    })


async def handle_unwatch_group(request: web.Request) -> web.Response:
    """DELETE /api/threat-intel/groups/{id}/watch — remove from watchlist."""
    await _ensure_engine()
    group_id = request.match_info["id"]
    async with get_session() as session:
        removed = await remove_from_watchlist(
            session, group_id=group_id, actor_id=DEFAULT_ACTOR
        )
    return web.json_response({
        "group_id": group_id,
        "watched": False,
        "removed": removed,
    })


# ---------------------------------------------------------------------------
# Threat Infrastructure IPs
# ---------------------------------------------------------------------------

async def handle_list_ips(request: web.Request) -> web.Response:
    """GET /api/threat-intel/ips — paginated C2 IP list."""
    await _ensure_engine()
    group_id = _query_param(request, "group_id")
    ip_type = _query_param(request, "ip_type")
    status = _query_param(request, "status")
    q = _query_param(request, "q")
    page = _int_param(request, "page", 1)
    page_size = _int_param(request, "page_size", 20)

    async with get_session() as session:
        result = await list_threat_infra_ips(
            session,
            group_id=group_id,
            ip_type=ip_type,
            status=status,
            q=q,
            page=page,
            page_size=page_size,
        )
    return web.json_response(result)


# ---------------------------------------------------------------------------
# Threat Vulnerabilities
# ---------------------------------------------------------------------------

async def handle_list_vulns(request: web.Request) -> web.Response:
    """GET /api/threat-intel/vulns — paginated vulnerability list."""
    await _ensure_engine()
    q = _query_param(request, "q")
    severity = _query_param(request, "severity")
    is_supply_chain = _bool_param(request, "is_supply_chain")
    is_cisa_kev = _bool_param(request, "is_cisa_kev")
    has_poc = _bool_param(request, "has_poc")
    exploit_available = _bool_param(request, "exploit_available")
    page = _int_param(request, "page", 1)
    page_size = _int_param(request, "page_size", 20)

    async with get_session() as session:
        result = await list_threat_vulns(
            session,
            q=q,
            severity=severity,
            is_supply_chain=is_supply_chain,
            is_cisa_kev=is_cisa_kev,
            has_poc=has_poc,
            exploit_available=exploit_available,
            page=page,
            page_size=page_size,
        )
    return web.json_response(result)


# ---------------------------------------------------------------------------
# Malware Families
# ---------------------------------------------------------------------------

async def handle_list_malware(request: web.Request) -> web.Response:
    """GET /api/threat-intel/malware — paginated malware family list."""
    await _ensure_engine()
    group_id = _query_param(request, "group_id")
    malware_type = _query_param(request, "type")
    q = _query_param(request, "q")
    page = _int_param(request, "page", 1)
    page_size = _int_param(request, "page_size", 20)

    async with get_session() as session:
        result = await list_threat_malware(
            session,
            group_id=group_id,
            type=malware_type,
            q=q,
            page=page,
            page_size=page_size,
        )
    return web.json_response(result)


# ---------------------------------------------------------------------------
# Maritime Events
# ---------------------------------------------------------------------------

async def handle_list_maritime(request: web.Request) -> web.Response:
    """GET /api/threat-intel/maritime — paginated maritime event list."""
    await _ensure_engine()
    event_type = _query_param(request, "event_type")
    severity = _query_param(request, "severity")
    verification_status = _query_param(request, "verification_status")
    from_date = _query_param(request, "from")
    to_date = _query_param(request, "to")
    page = _int_param(request, "page", 1)
    page_size = _int_param(request, "page_size", 20)

    # Parse date params
    from_dt = None
    to_dt = None
    if from_date:
        try:
            from_dt = datetime.fromisoformat(from_date)
        except ValueError:
            pass
    if to_date:
        try:
            to_dt = datetime.fromisoformat(to_date)
        except ValueError:
            pass

    async with get_session() as session:
        result = await list_maritime_events(
            session,
            event_type=event_type,
            severity=severity,
            from_date=from_dt,
            to_date=to_dt,
            verification_status=verification_status,
            page=page,
            page_size=page_size,
        )
    return web.json_response(result)


# ---------------------------------------------------------------------------
# Feed Pull Runs
# ---------------------------------------------------------------------------

async def handle_list_feed_runs(request: web.Request) -> web.Response:
    """GET /api/threat-intel/feeds/runs — list feed pull run records."""
    await _ensure_engine()
    source = _query_param(request, "source")
    status = _query_param(request, "status")
    page = _int_param(request, "page", 1)
    page_size = _int_param(request, "page_size", 20)

    async with get_session() as session:
        result = await list_feed_pull_runs(
            session,
            source=source,
            status=status,
            page=page,
            page_size=page_size,
        )
    return web.json_response(result)


async def handle_trigger_feed_pull(request: web.Request) -> web.Response:
    """POST /api/threat-intel/feeds/pull — manually trigger a feed pull.

    Body: ``{"source": "cisa_kev" | "threatfox" | "mitre"}``
    Returns the feed pull run summary.
    """
    await _ensure_engine()
    try:
        body = await request.json()
    except Exception:
        return _error(400, "invalid_body", "Request body must be JSON")

    source = body.get("source", "").strip()
    if not source:
        return _error(400, "missing_source", "Field 'source' is required")

    valid_sources = {"cisa_kev", "threatfox", "mitre"}
    if source not in valid_sources:
        return _error(
            400, "invalid_source",
            f"Source must be one of: {', '.join(sorted(valid_sources))}"
        )

    # Import the appropriate feed puller
    from secbot.threat_intel.feeds import (
        import_mitre_groups,
        pull_cisa_kev,
        pull_threatfox,
    )

    async with get_session() as session:
        if source == "mitre":
            result = await import_mitre_groups(session, trigger="manual")
        elif source == "cisa_kev":
            result = await pull_cisa_kev(session, trigger="manual")
        elif source == "threatfox":
            result = await pull_threatfox(session, trigger="manual")
        else:
            return _error(400, "invalid_source", f"Unknown source: {source}")

    return web.json_response(result)


# ---------------------------------------------------------------------------
# Config: Industry CPE
# ---------------------------------------------------------------------------

async def handle_list_industry_cpes(request: web.Request) -> web.Response:
    """GET /api/threat-intel/config/industry-cpes — list industry CPE entries."""
    await _ensure_engine()
    async with get_session() as session:
        result = await session.execute(
            select(IndustryCPE).order_by(IndustryCPE.industry_tag, IndustryCPE.product_name)
        )
        rows = result.scalars().all()

    items = [
        {
            "id": row.id,
            "cpe_string": row.cpe_string,
            "product_name": row.product_name,
            "vendor": row.vendor,
            "industry_tag": row.industry_tag,
            "confidence": row.confidence,
            "source": row.source,
            "note": row.note,
        }
        for row in rows
    ]
    return web.json_response({"items": items, "total": len(items)})


async def handle_add_industry_cpe(request: web.Request) -> web.Response:
    """POST /api/threat-intel/config/industry-cpes — add an industry CPE."""
    await _ensure_engine()
    try:
        body = await request.json()
    except Exception:
        return _error(400, "invalid_body", "Request body must be JSON")

    cpe_string = body.get("cpe_string", "").strip()
    product_name = body.get("product_name", "").strip()
    if not cpe_string or not product_name:
        return _error(400, "missing_fields", "cpe_string and product_name are required")

    cpe = IndustryCPE(
        cpe_string=cpe_string,
        product_name=product_name,
        vendor=body.get("vendor"),
        industry_tag=body.get("industry_tag", "maritime"),
        confidence=body.get("confidence", 0.8),
        source=body.get("source", "manual"),
        note=body.get("note"),
    )
    async with get_session() as session:
        session.add(cpe)
        await session.flush()
        cpe_id = cpe.id

    return web.json_response({
        "id": cpe_id,
        "cpe_string": cpe_string,
        "product_name": product_name,
        "message": "Industry CPE added",
    })


# ---------------------------------------------------------------------------
# Config: APT Aliases
# ---------------------------------------------------------------------------

async def handle_list_apt_aliases(request: web.Request) -> web.Response:
    """GET /api/threat-intel/config/aliases — list APT alias mappings."""
    await _ensure_engine()
    from secbot.threat_intel.models import AptAlias
    async with get_session() as session:
        result = await session.execute(
            select(AptAlias).order_by(AptAlias.alias_name)
        )
        rows = result.scalars().all()

    items = [
        {
            "id": row.id,
            "group_id": row.group_id,
            "alias_name": row.alias_name,
            "naming_org": row.naming_org,
            "confidence": row.confidence,
            "source_url": row.source_url,
        }
        for row in rows
    ]
    return web.json_response({"items": items, "total": len(items)})


async def handle_add_apt_alias(request: web.Request) -> web.Response:
    """POST /api/threat-intel/config/aliases — add an APT alias mapping."""
    await _ensure_engine()
    try:
        body = await request.json()
    except Exception:
        return _error(400, "invalid_body", "Request body must be JSON")

    alias_name = body.get("alias_name", "").strip()
    if not alias_name:
        return _error(400, "missing_alias", "Field 'alias_name' is required")

    async with get_session() as session:
        alias = await upsert_apt_alias(
            session,
            alias_name=alias_name,
            group_id=body.get("group_id"),
            naming_org=body.get("naming_org"),
            confidence=body.get("confidence", 0.8),
            source_url=body.get("source_url"),
        )
        alias_id = alias.id

    return web.json_response({
        "id": alias_id,
        "alias_name": alias_name,
        "message": "APT alias added/updated",
    })


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def register_routes(app: web.Application) -> None:
    """Register all /api/threat-intel/* routes on the given aiohttp app."""
    router = app.router

    # Overview
    router.add_get("/api/threat-intel/overview", handle_overview)

    # Groups
    router.add_get("/api/threat-intel/groups", handle_list_groups)
    router.add_get("/api/threat-intel/groups/{id}", handle_get_group)
    router.add_post("/api/threat-intel/groups/{id}/watch", handle_watch_group)
    router.add_delete("/api/threat-intel/groups/{id}/watch", handle_unwatch_group)

    # IPs
    router.add_get("/api/threat-intel/ips", handle_list_ips)

    # Vulnerabilities
    router.add_get("/api/threat-intel/vulns", handle_list_vulns)

    # Malware
    router.add_get("/api/threat-intel/malware", handle_list_malware)

    # Maritime
    router.add_get("/api/threat-intel/maritime", handle_list_maritime)

    # Feeds
    router.add_get("/api/threat-intel/feeds/runs", handle_list_feed_runs)
    router.add_post("/api/threat-intel/feeds/pull", handle_trigger_feed_pull)

    # Config
    router.add_get("/api/threat-intel/config/industry-cpes", handle_list_industry_cpes)
    router.add_post("/api/threat-intel/config/industry-cpes", handle_add_industry_cpe)
    router.add_get("/api/threat-intel/config/aliases", handle_list_apt_aliases)
    router.add_post("/api/threat-intel/config/aliases", handle_add_apt_alias)

    logger.info("Threat Intel API routes registered")

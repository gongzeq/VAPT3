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
from secbot.threat_intel.models import IndustryCPE, ThreatGroup
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


def _float_param(request: web.Request, name: str, default: float) -> float:
    try:
        return float(request.query.get(name, default))
    except (ValueError, TypeError):
        return default


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
        # Validate group exists before adding to watchlist
        result = await session.execute(
            select(ThreatGroup.id).where(ThreatGroup.id == group_id)
        )
        if result.scalar_one_or_none() is None:
            return _error(404, "not_found", f"Threat group {group_id} not found")

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

    valid_sources = {
        "cisa_kev", "threatfox", "mitre", "nvd", "malwarebazaar",
        "feodo", "otx", "exploit_db", "ukmto", "recaap", "imo", "expiry",
    }
    if source not in valid_sources:
        return _error(
            400, "invalid_source",
            f"Source must be one of: {', '.join(sorted(valid_sources))}"
        )

    # Import the appropriate feed puller
    from secbot.threat_intel.feeds import (
        import_mitre_groups,
        pull_cisa_kev,
        pull_exploit_db,
        pull_feodo,
        pull_malwarebazaar,
        pull_nvd,
        pull_otx,
        pull_threatfox,
    )

    async with get_session() as session:
        if source == "mitre":
            result = await import_mitre_groups(session, trigger="manual")
        elif source == "cisa_kev":
            result = await pull_cisa_kev(session, trigger="manual")
        elif source == "threatfox":
            result = await pull_threatfox(session, trigger="manual")
        elif source == "nvd":
            result = await pull_nvd(session, trigger="manual")
        elif source == "malwarebazaar":
            result = await pull_malwarebazaar(session, trigger="manual")
        elif source == "feodo":
            result = await pull_feodo(session, trigger="manual")
        elif source == "otx":
            result = await pull_otx(session, trigger="manual")
        elif source == "exploit_db":
            result = await pull_exploit_db(session, trigger="manual")
        elif source in ("ukmto", "recaap", "imo"):
            from secbot.threat_intel.feeds import pull_maritime
            result = await pull_maritime(session, trigger="manual", source=source)
        elif source == "expiry":
            from secbot.threat_intel.repo import run_expiry_sweep
            result = await run_expiry_sweep(session)
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
        alias, _created = await upsert_apt_alias(
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
# Graph API (P1)
# ---------------------------------------------------------------------------

async def handle_get_graph(request: web.Request) -> web.Response:
    """GET /api/threat-intel/graph -- knowledge graph data."""
    await _ensure_engine()
    group_id = _query_param(request, "group_id")
    watched = _bool_param(request, "watched")
    group_ids = _query_param(request, "group_ids")
    top_n = _int_param(request, "top_n", 30)
    min_confidence = _float_param(request, "min_confidence", 0.0)
    node_types = _query_param(request, "node_types")
    expand_cluster = _query_param(request, "expand_cluster")

    # Validate: exactly one mode
    modes = sum(1 for x in [group_id, watched, group_ids] if x)
    if modes != 1:
        return _error(400, "invalid_mode", "Provide exactly one of: group_id, watched=true, group_ids")

    from secbot.threat_intel.repo import get_graph_data

    async with get_session() as session:
        data = await get_graph_data(
            session,
            group_id=group_id,
            watched=bool(watched),
            group_ids=group_ids.split(",") if group_ids else None,
            actor_id=DEFAULT_ACTOR,
            top_n=top_n,
            min_confidence=min_confidence,
            node_types=node_types.split(",") if node_types else None,
            expand_cluster=expand_cluster,
        )
    return web.json_response(data)


# ---------------------------------------------------------------------------
# Detail APIs (P1)
# ---------------------------------------------------------------------------

async def handle_get_vuln_detail(request: web.Request) -> web.Response:
    """GET /api/threat-intel/vulns/{id} -- vulnerability detail."""
    await _ensure_engine()
    vuln_id = request.match_info["id"]
    from secbot.threat_intel.repo import get_threat_vuln
    async with get_session() as session:
        data = await get_threat_vuln(session, vuln_id)
    if data is None:
        return _error(404, "not_found", f"Vulnerability {vuln_id} not found")
    return web.json_response(data)


async def handle_get_ip_detail(request: web.Request) -> web.Response:
    """GET /api/threat-intel/ips/{id} -- IP detail."""
    await _ensure_engine()
    ip_id = request.match_info["id"]
    from secbot.threat_intel.repo import get_threat_infra_ip_detail
    async with get_session() as session:
        data = await get_threat_infra_ip_detail(session, ip_id)
    if data is None:
        return _error(404, "not_found", f"IP {ip_id} not found")
    return web.json_response(data)


async def handle_get_malware_detail(request: web.Request) -> web.Response:
    """GET /api/threat-intel/malware/{id} -- malware detail."""
    await _ensure_engine()
    malware_id = request.match_info["id"]
    from secbot.threat_intel.repo import get_threat_malware_detail
    async with get_session() as session:
        data = await get_threat_malware_detail(session, malware_id)
    if data is None:
        return _error(404, "not_found", f"Malware {malware_id} not found")
    return web.json_response(data)


# ---------------------------------------------------------------------------
# Batch Alias Import (P1)
# ---------------------------------------------------------------------------

async def handle_batch_import_aliases(request: web.Request) -> web.Response:
    """POST /api/threat-intel/config/aliases/batch -- batch upsert APT aliases."""
    await _ensure_engine()
    try:
        body = await request.json()
    except Exception:
        return _error(400, "invalid_body", "Request body must be JSON")

    aliases = body.get("aliases", [])
    if not aliases or not isinstance(aliases, list):
        return _error(400, "invalid_body", "Field 'aliases' must be a non-empty array")

    from secbot.threat_intel.models import ThreatGroup
    async with get_session() as session:
        # Build mitre_id -> group_id lookup
        result = await session.execute(select(ThreatGroup.id, ThreatGroup.mitre_id))
        mitre_to_group = {row.mitre_id: row.id for row in result if row.mitre_id}

        inserted = 0
        updated = 0
        failed = 0
        errors: list[dict] = []

        for entry in aliases:
            try:
                alias_name = entry.get("alias_name", "").strip()
                if not alias_name:
                    failed += 1
                    errors.append({"alias_name": "(empty)", "error": "alias_name is required"})
                    continue

                mitre_id = entry.get("mitre_id")
                group_id = mitre_to_group.get(mitre_id) if mitre_id else entry.get("group_id")

                _, created = await upsert_apt_alias(
                    session,
                    alias_name=alias_name,
                    group_id=group_id,
                    naming_org=entry.get("naming_org"),
                    confidence=entry.get("confidence", 0.8),
                    source_url=entry.get("source_url"),
                )
                if created:
                    inserted += 1
                else:
                    updated += 1
            except Exception as exc:
                failed += 1
                errors.append({"alias_name": entry.get("alias_name", "?"), "error": str(exc)})

    return web.json_response({
        "total": len(aliases),
        "inserted": inserted,
        "updated": updated,
        "failed": failed,
        "errors": errors,
    })


# ---------------------------------------------------------------------------
# CPE Delete (P1)
# ---------------------------------------------------------------------------

async def handle_delete_industry_cpe(request: web.Request) -> web.Response:
    """DELETE /api/threat-intel/config/industry-cpes/{id} -- remove an industry CPE."""
    await _ensure_engine()
    try:
        cpe_id = int(request.match_info["id"])
    except (ValueError, TypeError):
        return _error(400, "invalid_id", "CPE id must be an integer")
    async with get_session() as session:
        result = await session.execute(
            select(IndustryCPE).where(IndustryCPE.id == cpe_id)
        )
        cpe = result.scalar_one_or_none()
        if cpe is None:
            return _error(404, "not_found", f"Industry CPE {cpe_id} not found")
        await session.delete(cpe)
    return web.json_response({"id": cpe_id, "deleted": True})


# ---------------------------------------------------------------------------
# Maritime Review (P2)
# ---------------------------------------------------------------------------

async def handle_review_maritime(request: web.Request) -> web.Response:
    """PATCH /api/threat-intel/maritime/{id} -- update verification status."""
    await _ensure_engine()
    event_id = request.match_info["id"]
    try:
        body = await request.json()
    except Exception:
        return _error(400, "invalid_body", "Request body must be JSON")

    new_status = body.get("verification_status")
    valid_statuses = {"unreviewed", "confirmed", "dismissed"}
    if new_status not in valid_statuses:
        return _error(
            400, "invalid_status",
            f"verification_status must be one of: {', '.join(sorted(valid_statuses))}",
        )

    from secbot.threat_intel.models import MaritimeEvent
    async with get_session() as session:
        result = await session.execute(
            select(MaritimeEvent).where(MaritimeEvent.id == event_id)
        )
        event = result.scalar_one_or_none()
        if event is None:
            return _error(404, "not_found", f"Maritime event {event_id} not found")
        event.verification_status = new_status

    return web.json_response({
        "id": event_id,
        "verification_status": new_status,
        "updated": True,
    })


# ---------------------------------------------------------------------------
# Review Queue (P2)
# ---------------------------------------------------------------------------

async def handle_review_queue_list(request: web.Request) -> web.Response:
    """GET /api/threat-intel/review-queue -- list low-confidence records."""
    await _ensure_engine()
    entity_type = _query_param(request, "type", "ip") or "ip"
    max_conf = _float_param(request, "max_confidence", 0.65)
    page = _int_param(request, "page", 1)
    page_size = _int_param(request, "page_size", 20)

    from secbot.threat_intel.repo import get_review_queue
    async with get_session() as session:
        data = await get_review_queue(
            session, entity_type=entity_type,
            max_confidence=max_conf, page=page, page_size=page_size,
        )
    return web.json_response(data)


async def handle_review_action(request: web.Request) -> web.Response:
    """POST /api/threat-intel/review-queue/{id}/action -- perform review action."""
    await _ensure_engine()
    item_id = request.match_info["id"]
    try:
        body = await request.json()
    except Exception:
        return _error(400, "invalid_body", "Request body must be JSON")

    action = body.get("action")
    if action not in ("confirm_mapping", "confirm_event", "remap", "dismiss"):
        return _error(400, "invalid_action", f"Unknown action: {action}")

    from secbot.threat_intel.repo import apply_review_action
    async with get_session() as session:
        result = await apply_review_action(
            session, item_id=item_id, action=action, body=body,
        )
    if result is None:
        return _error(404, "not_found", f"Review item {item_id} not found")
    return web.json_response(result)


# ---------------------------------------------------------------------------
# Expiry Sweep (P2)
# ---------------------------------------------------------------------------

async def handle_trigger_expiry_sweep(request: web.Request) -> web.Response:
    """POST /api/threat-intel/expiry-sweep -- trigger data expiry sweep."""
    await _ensure_engine()
    from secbot.threat_intel.repo import run_expiry_sweep
    async with get_session() as session:
        result = await run_expiry_sweep(session)
    return web.json_response(result)


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
    router.add_get("/api/threat-intel/ips/{id}", handle_get_ip_detail)

    # Vulnerabilities
    router.add_get("/api/threat-intel/vulns", handle_list_vulns)
    router.add_get("/api/threat-intel/vulns/{id}", handle_get_vuln_detail)

    # Malware
    router.add_get("/api/threat-intel/malware", handle_list_malware)
    router.add_get("/api/threat-intel/malware/{id}", handle_get_malware_detail)

    # Maritime
    router.add_get("/api/threat-intel/maritime", handle_list_maritime)
    router.add_patch("/api/threat-intel/maritime/{id}", handle_review_maritime)

    # Graph (P1)
    router.add_get("/api/threat-intel/graph", handle_get_graph)

    # Feeds
    router.add_get("/api/threat-intel/feeds/runs", handle_list_feed_runs)
    router.add_post("/api/threat-intel/feeds/pull", handle_trigger_feed_pull)

    # Config
    router.add_get("/api/threat-intel/config/industry-cpes", handle_list_industry_cpes)
    router.add_post("/api/threat-intel/config/industry-cpes", handle_add_industry_cpe)
    router.add_delete("/api/threat-intel/config/industry-cpes/{id}", handle_delete_industry_cpe)
    router.add_get("/api/threat-intel/config/aliases", handle_list_apt_aliases)
    router.add_post("/api/threat-intel/config/aliases", handle_add_apt_alias)
    router.add_post("/api/threat-intel/config/aliases/batch", handle_batch_import_aliases)

    # Review Queue (P2)
    router.add_get("/api/threat-intel/review-queue", handle_review_queue_list)
    router.add_post("/api/threat-intel/review-queue/{id}/action", handle_review_action)

    # Expiry Sweep (P2)
    router.add_post("/api/threat-intel/expiry-sweep", handle_trigger_expiry_sweep)

    logger.info("Threat Intel API routes registered")

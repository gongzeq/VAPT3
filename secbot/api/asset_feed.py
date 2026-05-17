"""Per-chat asset feed snapshot API handler.

Mirrors :mod:`secbot.api.blackboard`. The asset feed is the real-time
discovery channel populated by sub-agents via ``asset_push``; this
endpoint lets the WebUI's Right Rail "Asset Feed" tab backfill on
mount or refresh without depending on a WebSocket increment stream.

Wiring:

* ``request.app["asset_feed_registry"]`` is the
  :class:`secbot.agent.asset_feed.AssetFeedRegistry` instance owned by
  the active :class:`secbot.agent.loop.AgentLoop`. ``server.create_app``
  injects it on app construction.

* When the registry is missing (e.g. legacy ``aiohttp`` apps), the
  handler returns a stable empty payload rather than 500.
"""

from __future__ import annotations

from typing import Any

from aiohttp import web


async def handle_get_assets(request: web.Request) -> web.Response:
    """GET /api/assets?chat_id=...&kind=...&since_id=...

    Behavior:

    * 400 when ``chat_id`` query is missing.
    * 200 ``{"chat_id": ..., "entries": [], "latest_id": 0, "counts": {}}``
      when the registry has no feed for that chat (or registry missing).
      The handler does NOT auto-create a feed on read so the registry
      doesn't accumulate empty feeds from spurious queries.
    * 200 with the filtered slice otherwise. Each entry retains the
      canonical shape from :meth:`AssetEntry.to_dict`
      (``id / kind / agent_name / payload / created_at``).
    """
    chat_id = request.query.get("chat_id", "").strip()
    if not chat_id:
        return web.json_response({"error": "missing chat_id"}, status=400)

    kind_raw = request.query.get("kind", "").strip()
    kind: str | None = kind_raw.lower() if kind_raw else None

    since_raw = request.query.get("since_id", "").strip()
    since_id: int | None = None
    if since_raw:
        try:
            parsed = int(since_raw)
            if parsed >= 0:
                since_id = parsed
        except ValueError:
            pass

    empty_payload = {
        "chat_id": chat_id,
        "entries": [],
        "latest_id": 0,
        "counts": {},
    }

    registry: Any | None = request.app.get("asset_feed_registry")
    if registry is None:
        return web.json_response(empty_payload)

    try:
        feed = await registry.get(chat_id)
    except Exception:
        return web.json_response(empty_payload)

    if feed is None:
        return web.json_response(empty_payload)

    try:
        entries = await feed.since(since_id=since_id, kind=kind, limit=500)
        counts = await feed.counts_by_kind()
    except Exception:
        entries = []
        counts = {}

    return web.json_response(
        {
            "chat_id": chat_id,
            "entries": [e.to_dict() for e in entries],
            "latest_id": feed.latest_id,
            "counts": counts,
        }
    )


def register_asset_feed_routes(app: web.Application) -> None:
    """Register the asset feed snapshot route on *app*.

    Mirrors :func:`secbot.api.blackboard.register_blackboard_routes`.
    Callers must have populated ``app["asset_feed_registry"]`` before
    requests arrive; when absent the handler degrades to an empty
    entry list.
    """
    app.router.add_get("/api/assets", handle_get_assets)

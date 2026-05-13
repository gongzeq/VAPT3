"""Per-chat blackboard snapshot API handler.

Spec: ``.trellis/spec/backend/dashboard-aggregation.md`` §2.7.

This module exposes ``GET /api/blackboard?chat_id=...`` so the WebUI's Right
Rail Blackboard tab can backfill on mount/refresh without depending on the
WebSocket increment stream.

Wiring:

* ``request.app["blackboard_registry"]`` is the
  :class:`secbot.agent.blackboard.BlackboardRegistry` instance owned by the
  active :class:`secbot.agent.loop.AgentLoop`. ``server.create_app`` injects
  it on app construction; the WebSocket channel mirrors the same surface from
  its own dispatcher (see :mod:`secbot.channels.websocket`).

* When the registry is missing (e.g. legacy ``aiohttp`` apps that haven't been
  upgraded yet), the handler returns a stable empty payload rather than 500
  so the UI surface stays predictable.
"""

from __future__ import annotations

from typing import Any

from aiohttp import web


async def handle_get_blackboard(request: web.Request) -> web.Response:
    """GET /api/blackboard?chat_id=...

    Behavior:

    * 400 when ``chat_id`` query is missing.
    * 200 with ``{"chat_id": ..., "entries": []}`` when the registry has no
      board for that chat. We deliberately do **not** create a board on read
      so the registry doesn't accumulate empty boards from spurious queries.
    * 200 with the entry list otherwise. Each entry retains the canonical
      shape produced by :meth:`Blackboard.to_dict_list`
      (``id / agent_name / text / timestamp / kind``).
    """
    chat_id = request.query.get("chat_id", "").strip()
    if not chat_id:
        return web.json_response({"error": "missing chat_id"}, status=400)

    registry: Any | None = request.app.get("blackboard_registry")
    if registry is None:
        return web.json_response({"chat_id": chat_id, "entries": []})

    try:
        board = await registry.get(chat_id)
    except Exception:
        # Lookup is the only registry op invoked here; a failure means the
        # registry itself is unhealthy. Fall back to empty rather than 500
        # so the surface stays stable for the dashboard.
        return web.json_response({"chat_id": chat_id, "entries": []})

    if board is None:
        return web.json_response({"chat_id": chat_id, "entries": []})

    try:
        entries = await board.to_dict_list()
    except Exception:
        entries = []
    return web.json_response({"chat_id": chat_id, "entries": entries})


def register_blackboard_routes(app: web.Application) -> None:
    """Register the blackboard snapshot route on *app*.

    Mirrors :func:`secbot.api.agents.register_agent_routes`. Callers must
    have populated ``app["blackboard_registry"]`` before requests arrive;
    when absent the handler degrades to an empty entry list.
    """
    app.router.add_get("/api/blackboard", handle_get_blackboard)

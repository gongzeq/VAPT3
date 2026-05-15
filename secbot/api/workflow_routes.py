"""REST handlers for the workflow engine.

Mounted onto the aiohttp :class:`~aiohttp.web.Application` created by
:func:`secbot.api.server.create_app` when a ``WorkflowService`` is wired
in. All paths are rooted at ``/api/workflows`` and speak camelCase to
match ``.trellis/tasks/05-11-workflow-builder-ui/api-spec.md``.

Design notes:

* Handlers ONLY orchestrate :class:`WorkflowService`; business logic
  stays in the service / runner / executors. That keeps the HTTP layer
  a thin translation shell (spec §2).
* Errors surface as ``{"error": {"code": "<prefix.detail>", "message":
  "<human>"}}`` with an HTTP status chosen per api-spec.md §4.
* ``_tools`` / ``_agents`` / ``_templates`` live next to CRUD so the
  frontend only has to hit ``/api/workflows/*``.
"""

from __future__ import annotations

import json as _json
import logging
from typing import Any

from aiohttp import web

from secbot.workflow import (
    Workflow,
    WorkflowInput,
    WorkflowService,
    WorkflowServiceError,
    WorkflowStep,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _error(status: int, code: str, message: str) -> web.Response:
    return web.json_response(
        {"error": {"code": code, "message": message}}, status=status
    )


def _error_from_service(exc: WorkflowServiceError) -> web.Response:
    """Map a :class:`WorkflowServiceError` to the right HTTP status.

    The service uses ``workflow.validation.<topic>`` / ``workflow.
    validation.not_found`` prefixes; translate to the HTTP statuses
    documented in api-spec.md §4.
    """
    msg = str(exc)
    code, _, detail = msg.partition(": ")
    if code.endswith(".not_found"):
        return _error(404, code, detail or msg)
    if code.endswith(".cron_unavailable"):
        return _error(503, code, detail or msg)
    return _error(400, code or "workflow.validation.generic", detail or msg)


def _service(request: web.Request) -> WorkflowService | None:
    return request.app.get("workflow_service")


def _require_service(request: web.Request) -> WorkflowService:
    svc = _service(request)
    if svc is None:
        raise _HTTPServiceUnavailable()
    return svc


class _HTTPServiceUnavailable(Exception):
    """Internal marker: workflow service was not wired on this app."""


async def _read_json(request: web.Request) -> dict[str, Any]:
    """Parse request body as JSON object, returning ``{}`` on empty body."""
    if not request.can_read_body:
        return {}
    raw = await request.read()
    if not raw:
        return {}
    try:
        data = _json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, _json.JSONDecodeError) as exc:
        raise _BadJSON(str(exc)) from exc
    if not isinstance(data, dict):
        raise _BadJSON("body must be a JSON object")
    return data


class _BadJSON(Exception):
    """Body could not be parsed as a JSON object."""


def _service_unavailable() -> web.Response:
    return _error(503, "workflow.unavailable", "workflow service not wired")


# ---------------------------------------------------------------------------
# Workflow <-> dict helpers
# ---------------------------------------------------------------------------


def _build_inputs(raw: Any) -> list[WorkflowInput]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise _BadJSON("inputs must be a list")
    out: list[WorkflowInput] = []
    for item in raw:
        if not isinstance(item, dict):
            raise _BadJSON("each input must be an object")
        out.append(
            WorkflowInput(
                name=str(item.get("name", "")),
                label=str(item.get("label", "")),
                type=item.get("type", "string"),
                required=bool(item.get("required", False)),
                default=item.get("default"),
                description=item.get("description"),
                enum_values=item.get("enumValues") or item.get("enum_values"),
            )
        )
    return out


def _build_steps(raw: Any) -> list[WorkflowStep]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise _BadJSON("steps must be a list")
    out: list[WorkflowStep] = []
    for item in raw:
        if not isinstance(item, dict):
            raise _BadJSON("each step must be an object")
        out.append(
            WorkflowStep(
                id=str(item.get("id", "")),
                name=str(item.get("name", "")),
                kind=item.get("kind", "tool"),
                ref=str(item.get("ref", "")),
                args=dict(item.get("args") or {}),
                condition=item.get("condition"),
                on_error=item.get("onError") or item.get("on_error") or "stop",
                retry=int(item.get("retry") or 0),
            )
        )
    return out


def _apply_body(wf: Workflow, body: dict[str, Any]) -> Workflow:
    """Apply mutable fields from ``body`` onto ``wf`` in-place.

    ``id``, ``createdAtMs`` and ``scheduleRef`` are never clobbered by
    the body — they're owned by the server / service.
    """
    if "name" in body:
        wf.name = str(body["name"] or "").strip()
    if "description" in body:
        wf.description = str(body["description"] or "")
    if "tags" in body:
        tags = body["tags"]
        if tags is not None and not isinstance(tags, list):
            raise _BadJSON("tags must be a list")
        wf.tags = [str(t) for t in (tags or [])]
    if "inputs" in body:
        wf.inputs = _build_inputs(body.get("inputs"))
    if "steps" in body:
        wf.steps = _build_steps(body.get("steps"))
    # updatedAtMs is refreshed by the caller right before save.
    return wf


# ---------------------------------------------------------------------------
# CRUD handlers
# ---------------------------------------------------------------------------


async def handle_list(request: web.Request) -> web.Response:
    try:
        svc = _require_service(request)
    except _HTTPServiceUnavailable:
        return _service_unavailable()
    items = await svc.list_workflows()
    query = request.rel_url.query
    tag = (query.get("tag") or "").strip().lower()
    search = (query.get("search") or "").strip().lower()
    filtered = []
    for wf in items:
        if tag and tag not in {t.lower() for t in wf.tags}:
            continue
        if search and search not in wf.name.lower() and search not in wf.description.lower():
            continue
        filtered.append(wf)
    scheduled = sum(1 for wf in items if wf.schedule_ref)
    return web.json_response(
        {
            "items": [wf.to_dict() for wf in filtered],
            "total": len(filtered),
            "stats": {"running": 0, "scheduled": scheduled, "failed24h": 0},
        }
    )


async def handle_create(request: web.Request) -> web.Response:
    try:
        svc = _require_service(request)
    except _HTTPServiceUnavailable:
        return _service_unavailable()
    try:
        body = await _read_json(request)
    except _BadJSON as exc:
        return _error(400, "workflow.validation.body", str(exc))
    try:
        wf = Workflow.new(
            name=str(body.get("name") or "").strip(),
            description=str(body.get("description") or ""),
            tags=[str(t) for t in (body.get("tags") or [])],
            inputs=_build_inputs(body.get("inputs")),
            steps=_build_steps(body.get("steps")),
        )
    except _BadJSON as exc:
        return _error(400, "workflow.validation.body", str(exc))
    try:
        saved = await svc.save_workflow(wf)
    except WorkflowServiceError as exc:
        return _error_from_service(exc)
    return web.json_response(saved.to_dict(), status=201)


async def handle_get(request: web.Request) -> web.Response:
    try:
        svc = _require_service(request)
    except _HTTPServiceUnavailable:
        return _service_unavailable()
    wf_id = request.match_info["id"]
    wf = await svc.get_workflow(wf_id)
    if wf is None:
        return _error(404, "workflow.not_found", f"workflow {wf_id} does not exist")
    return web.json_response(wf.to_dict())


async def handle_update(request: web.Request) -> web.Response:
    try:
        svc = _require_service(request)
    except _HTTPServiceUnavailable:
        return _service_unavailable()
    wf_id = request.match_info["id"]
    existing = await svc.get_workflow(wf_id)
    if existing is None:
        return _error(404, "workflow.not_found", f"workflow {wf_id} does not exist")
    try:
        body = await _read_json(request)
    except _BadJSON as exc:
        return _error(400, "workflow.validation.body", str(exc))
    try:
        _apply_body(existing, body)
    except _BadJSON as exc:
        return _error(400, "workflow.validation.body", str(exc))
    # Bump updatedAtMs so clients can detect staleness.
    from secbot.workflow.types import _now_ms  # type: ignore[attr-defined]

    existing.updated_at_ms = _now_ms()
    try:
        saved = await svc.save_workflow(existing)
    except WorkflowServiceError as exc:
        return _error_from_service(exc)
    return web.json_response(saved.to_dict())


async def handle_delete(request: web.Request) -> web.Response:
    try:
        svc = _require_service(request)
    except _HTTPServiceUnavailable:
        return _service_unavailable()
    wf_id = request.match_info["id"]
    removed = await svc.delete_workflow(wf_id)
    if not removed:
        return _error(404, "workflow.not_found", f"workflow {wf_id} does not exist")
    return web.json_response({"deleted": wf_id})


# ---------------------------------------------------------------------------
# Run + runs
# ---------------------------------------------------------------------------


async def handle_run(request: web.Request) -> web.Response:
    try:
        svc = _require_service(request)
    except _HTTPServiceUnavailable:
        return _service_unavailable()
    wf_id = request.match_info["id"]
    try:
        body = await _read_json(request)
    except _BadJSON as exc:
        return _error(400, "workflow.validation.body", str(exc))
    inputs = body.get("inputs") or {}
    if not isinstance(inputs, dict):
        return _error(400, "workflow.validation.inputs", "inputs must be an object")
    try:
        run = await svc.run(wf_id, inputs, trigger="api")
    except WorkflowServiceError as exc:
        return _error_from_service(exc)
    payload = run.to_dict()
    # api-spec §2.2 asks for a thin header; include the full run for
    # completeness so the client can update RunHistoryTab without a
    # follow-up fetch.
    payload["runId"] = run.id
    return web.json_response(payload)


async def handle_list_runs(request: web.Request) -> web.Response:
    try:
        svc = _require_service(request)
    except _HTTPServiceUnavailable:
        return _service_unavailable()
    wf_id = request.match_info["id"]
    wf = await svc.get_workflow(wf_id)
    if wf is None:
        return _error(404, "workflow.not_found", f"workflow {wf_id} does not exist")
    raw_limit = request.rel_url.query.get("limit")
    limit: int | None = None
    if raw_limit is not None:
        try:
            limit = max(1, min(500, int(raw_limit)))
        except (TypeError, ValueError):
            return _error(400, "workflow.validation.limit", "limit must be an integer")
    runs = await svc.list_runs(workflow_id=wf_id, limit=limit)
    return web.json_response({"items": [r.to_dict() for r in runs]})


async def handle_get_run(request: web.Request) -> web.Response:
    try:
        svc = _require_service(request)
    except _HTTPServiceUnavailable:
        return _service_unavailable()
    run_id = request.match_info["runId"]
    run = await svc.get_run(run_id)
    if run is None:
        return _error(404, "run.not_found", f"run {run_id} does not exist")
    return web.json_response(run.to_dict())


# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------


async def handle_schedule_set(request: web.Request) -> web.Response:
    try:
        svc = _require_service(request)
    except _HTTPServiceUnavailable:
        return _service_unavailable()
    wf_id = request.match_info["id"]
    try:
        body = await _read_json(request)
    except _BadJSON as exc:
        return _error(400, "workflow.validation.body", str(exc))
    try:
        schedule = _build_schedule(body)
    except _BadJSON as exc:
        return _error(400, "workflow.validation.schedule", str(exc))
    inputs = body.get("inputs") or {}
    if not isinstance(inputs, dict):
        return _error(400, "workflow.validation.inputs", "inputs must be an object")
    try:
        wf = await svc.attach_schedule(
            wf_id, schedule, inputs=inputs, name=body.get("name")
        )
    except WorkflowServiceError as exc:
        return _error_from_service(exc)
    return web.json_response(wf.to_dict())


async def handle_schedule_delete(request: web.Request) -> web.Response:
    try:
        svc = _require_service(request)
    except _HTTPServiceUnavailable:
        return _service_unavailable()
    wf_id = request.match_info["id"]
    try:
        wf = await svc.detach_schedule(wf_id)
    except WorkflowServiceError as exc:
        return _error_from_service(exc)
    return web.json_response(wf.to_dict())


def _build_schedule(body: dict[str, Any]) -> Any:
    """Build a :class:`CronSchedule` from the REST body.

    Import lives here (not at module scope) so the workflow routes stay
    importable when the cron module is not available.
    """
    from secbot.cron.types import CronSchedule

    kind = body.get("kind")
    if kind not in ("cron", "every", "at"):
        raise _BadJSON(f"schedule.kind must be one of cron|every|at, got {kind!r}")

    expr = body.get("cronExpr") or body.get("expr")
    at_ms = body.get("atMs") or body.get("at_ms")
    every_ms = body.get("everyMs") or body.get("every_ms")
    tz = body.get("tz")

    if kind == "cron" and not expr:
        raise _BadJSON("schedule.cronExpr is required when kind=cron")
    if kind == "every" and not every_ms:
        raise _BadJSON("schedule.everyMs is required when kind=every")
    if kind == "at" and not at_ms:
        raise _BadJSON("schedule.atMs is required when kind=at")

    return CronSchedule(
        kind=kind,
        expr=expr,
        at_ms=int(at_ms) if at_ms is not None else None,
        every_ms=int(every_ms) if every_ms is not None else None,
        tz=tz,
    )


# ---------------------------------------------------------------------------
# Metadata endpoints
# ---------------------------------------------------------------------------


async def handle_tools(request: web.Request) -> web.Response:
    tool_registry = request.app.get("workflow_tool_registry")
    if tool_registry is None:
        return web.json_response({"items": []})
    items: list[dict[str, Any]] = []
    for name in getattr(tool_registry, "tool_names", []):
        tool = tool_registry.get(name)
        if tool is None:
            continue
        items.append(
            {
                "name": tool.name,
                "title": getattr(tool, "display_name", tool.name),
                "description": tool.description,
                "inputSchema": tool.parameters,
                "outputSchema": getattr(tool, "output_schema", {}) or {},
            }
        )
    items.sort(key=lambda row: row["name"])
    return web.json_response({"items": items})


async def handle_agents(request: web.Request) -> web.Response:
    agent_registry = request.app.get("workflow_agent_registry")
    if agent_registry is None:
        return web.json_response({"items": []})
    items: list[dict[str, Any]] = []
    for spec in agent_registry:  # iterate spec dataclasses
        items.append(
            {
                "name": spec.name,
                "title": spec.display_name,
                "description": spec.description,
                "inputSchema": dict(spec.input_schema or {}),
                "outputSchema": dict(spec.output_schema or {}),
            }
        )
    items.sort(key=lambda row: row["name"])
    return web.json_response({"items": items})


async def handle_templates(request: web.Request) -> web.Response:
    """Return the built-in workflow templates.

    Catalogue lives in :mod:`secbot.workflow.templates` — a small Python
    module rather than a YAML asset because the templates declare a
    sizable amount of code (e.g. step1 / step3 inline scripts for the
    phishing-email workflow). PRD: ``.trellis/tasks/05-13-phishing-email
    -workflow/prd.md §R3``.
    """
    from secbot.workflow.templates import list_templates

    try:
        items = list_templates()
    except Exception:
        logger.exception("workflow.templates: unexpected build failure")
        items = []
    return web.json_response({"items": items})


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_routes(app: web.Application) -> None:
    """Attach every ``/api/workflows/*`` route to *app*.

    Safe to call multiple times during tests only when the app is
    recreated. The caller is responsible for setting
    ``app["workflow_service"]`` (and optionally ``workflow_tool_registry``
    / ``workflow_agent_registry``) before requests hit these handlers.
    """
    router = app.router
    # Metadata endpoints come BEFORE the generic ``/{id}`` routes so
    # literal ``_tools`` doesn't get captured as an id.
    router.add_get("/api/workflows/_tools", handle_tools)
    router.add_get("/api/workflows/_agents", handle_agents)
    router.add_get("/api/workflows/_templates", handle_templates)

    router.add_get("/api/workflows", handle_list)
    router.add_post("/api/workflows", handle_create)

    router.add_get("/api/workflows/{id}", handle_get)
    router.add_put("/api/workflows/{id}", handle_update)
    router.add_delete("/api/workflows/{id}", handle_delete)

    router.add_post("/api/workflows/{id}/run", handle_run)
    router.add_get("/api/workflows/{id}/runs", handle_list_runs)
    router.add_get("/api/workflows/{id}/runs/{runId}", handle_get_run)

    router.add_post("/api/workflows/{id}/schedule", handle_schedule_set)
    router.add_delete("/api/workflows/{id}/schedule", handle_schedule_delete)

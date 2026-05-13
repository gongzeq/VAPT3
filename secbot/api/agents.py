"""Agent and Skill CRUD API handlers."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from aiohttp import web

# ─── Name validation ─────────────────────────────────────────────────

SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _validate_name(name: str) -> web.Response | None:
    """Validate resource name. Returns error response if invalid, None if ok."""
    if not name or not SAFE_NAME_RE.match(name):
        return web.json_response(
            {"error": "Invalid name. Use [A-Za-z0-9_-], max 64 chars."},
            status=400,
        )
    return None


def _format_iso(ts: float | None) -> str | None:
    """Format an epoch-second timestamp as ISO-8601 UTC, or None when 0/missing."""
    if not ts:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


def _collect_runtime_status(
    subagent_manager: Any | None,
) -> dict[str, dict[str, Any]]:
    """Aggregate ``SubagentManager._task_statuses`` into ``agent_name → snapshot``.

    Used by ``/api/agents?include_status=true`` to enrich the static registry
    payload with runtime fields. Last write wins on heartbeat to keep
    multi-task races deterministic. Spec: dashboard-aggregation.md §2.6.
    """
    if subagent_manager is None:
        return {}
    try:
        raw_statuses = subagent_manager._task_statuses  # noqa: SLF001
    except Exception:
        return {}
    by_agent: dict[str, dict[str, Any]] = {}
    for status in raw_statuses.values():
        agent_name = getattr(status, "agent_name", "") or ""
        if not agent_name:
            continue
        last_hb = getattr(status, "last_heartbeat_at", 0.0)
        prev = by_agent.get(agent_name)
        if prev is not None and prev.get("_hb", 0.0) >= last_hb:
            continue
        by_agent[agent_name] = {
            "status": "running",
            "current_task_id": status.task_id,
            "last_heartbeat_at": _format_iso(last_hb),
            "_hb": last_hb,
        }
    return by_agent


# ─── Agents ──────────────────────────────────────────────────────────


async def handle_list_agents(request: web.Request) -> web.Response:
    """GET /api/agents — List all registered expert agents.

    Default response is byte-stable: only the registry-derived fields, in
    insertion order. With ``?include_status=true`` each entry is enriched
    with ``status / current_task_id / last_heartbeat_at`` from the injected
    :class:`SubagentManager` snapshot. Spec:
    ``.trellis/spec/backend/dashboard-aggregation.md`` §2.6.
    """
    registry = request.app["agent_registry"]
    agents = []
    for spec in registry:
        agents.append({
            "name": spec.name,
            "display_name": spec.display_name,
            "description": spec.description,
            "scoped_skills": list(spec.scoped_skills),
            "max_iterations": spec.max_iterations,
            "source_path": str(spec.source_path) if spec.source_path else None,
            # PR3 availability contract. Defaults to available=True /
            # empty binaries when the registry was loaded without a
            # ``skills_root``.
            "available": spec.available,
            "required_binaries": list(spec.required_binaries),
            "missing_binaries": list(spec.missing_binaries),
        })

    include_status_raw = (request.query.get("include_status") or "").lower()
    if include_status_raw in {"1", "true", "yes"}:
        subagent_manager = request.app.get("subagent_manager")
        by_agent = _collect_runtime_status(subagent_manager)
        offline_default = subagent_manager is None
        for entry in agents:
            snap = by_agent.get(entry["name"])
            if snap is None:
                entry["status"] = "offline" if offline_default else "idle"
                entry["current_task_id"] = None
                entry["progress"] = None
                entry["last_heartbeat_at"] = None
            else:
                entry["status"] = snap["status"]
                entry["current_task_id"] = snap["current_task_id"]
                # progress is reserved for a future ScanProgress aggregation
                # pass — surface ``None`` for now so the schema is stable.
                # Spec: dashboard-aggregation.md §2.6 ("null unless running").
                entry["progress"] = None
                entry["last_heartbeat_at"] = snap["last_heartbeat_at"]
    return web.json_response({"agents": agents})


async def handle_get_agent(request: web.Request) -> web.Response:
    """GET /api/agents/{name} — Get agent details including YAML content."""
    name = request.match_info["name"]
    err = _validate_name(name)
    if err:
        return err
    registry = request.app["agent_registry"]

    if name not in registry:
        return web.json_response({"error": f"Agent '{name}' not found"}, status=404)

    spec = registry.get(name)
    # Read raw YAML content
    yaml_content = ""
    if spec.source_path and spec.source_path.is_file():
        yaml_content = spec.source_path.read_text(encoding="utf-8")

    return web.json_response({
        "name": spec.name,
        "display_name": spec.display_name,
        "description": spec.description,
        "scoped_skills": list(spec.scoped_skills),
        "input_schema": dict(spec.input_schema),
        "output_schema": dict(spec.output_schema),
        "system_prompt": spec.system_prompt,
        "max_iterations": spec.max_iterations,
        "emit_plan_steps": spec.emit_plan_steps,
        "yaml_content": yaml_content,
        "source_path": str(spec.source_path) if spec.source_path else None,
        # PR3 availability.
        "available": spec.available,
        "required_binaries": list(spec.required_binaries),
        "missing_binaries": list(spec.missing_binaries),
    })


async def handle_create_agent(request: web.Request) -> web.Response:
    """POST /api/agents — Create a new agent (writes YAML + prompt file)."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    agents_dir: Path = request.app["agents_dir"]

    # YAML direct mode — caller provides raw YAML content
    if "yaml_content" in body:
        import yaml as yaml_lib
        try:
            parsed = yaml_lib.safe_load(body["yaml_content"])
        except Exception as e:
            return web.json_response({"error": f"Invalid YAML: {e}"}, status=400)
        name = parsed.get("name", "")
        err = _validate_name(name)
        if err:
            return err
        yaml_path = agents_dir / f"{name}.yaml"
        if yaml_path.exists():
            return web.json_response({"error": f"Agent '{name}' already exists"}, status=409)
        yaml_path.write_text(body["yaml_content"], encoding="utf-8")
        # Handle system_prompt_file if present
        prompt_rel = parsed.get("system_prompt_file", "")
        if prompt_rel and body.get("system_prompt"):
            prompt_path = (agents_dir / prompt_rel).resolve()
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text(body["system_prompt"], encoding="utf-8")
        return web.json_response({"name": name, "restart_required": True}, status=201)

    # Validate required fields
    required = ["name", "display_name", "description", "system_prompt", "scoped_skills"]
    missing = [f for f in required if f not in body]
    if missing:
        return web.json_response({"error": f"Missing fields: {', '.join(missing)}"}, status=400)

    name = body["name"]
    err = _validate_name(name)
    if err:
        return err
    yaml_path = agents_dir / f"{name}.yaml"

    if yaml_path.exists():
        return web.json_response({"error": f"Agent '{name}' already exists"}, status=409)

    # Write system prompt file
    prompts_dir = agents_dir / "prompts"
    prompts_dir.mkdir(exist_ok=True)
    prompt_file = prompts_dir / f"{name}.md"
    prompt_file.write_text(body["system_prompt"], encoding="utf-8")

    # Provide defaults for optional schema fields
    input_schema = body.get("input_schema") or {"type": "object", "properties": {}}
    output_schema = body.get("output_schema") or {"type": "object", "properties": {}}

    # Build YAML content
    yaml_data = {
        "name": name,
        "display_name": body["display_name"],
        "description": body["description"],
        "system_prompt_file": f"prompts/{name}.md",
        "scoped_skills": body["scoped_skills"],
        "input_schema": input_schema,
        "output_schema": output_schema,
    }
    if "max_iterations" in body:
        yaml_data["max_iterations"] = body["max_iterations"]
    if "emit_plan_steps" in body:
        yaml_data["emit_plan_steps"] = body["emit_plan_steps"]

    yaml_path.write_text(yaml.dump(yaml_data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    return web.json_response({
        "name": name,
        "display_name": body["display_name"],
        "description": body["description"],
        "scoped_skills": body["scoped_skills"],
        "restart_required": True,
    }, status=201)


async def handle_update_agent(request: web.Request) -> web.Response:
    """PUT /api/agents/{name} — Update agent configuration."""
    name = request.match_info["name"]
    err = _validate_name(name)
    if err:
        return err
    registry = request.app["agent_registry"]
    agents_dir: Path = request.app["agents_dir"]

    if name not in registry:
        return web.json_response({"error": f"Agent '{name}' not found"}, status=404)

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    spec = registry.get(name)
    yaml_path = spec.source_path
    if not yaml_path or not yaml_path.is_file():
        return web.json_response({"error": "Agent source file not found"}, status=500)

    # If raw yaml_content is provided, write it directly
    if "yaml_content" in body:
        yaml_path.write_text(body["yaml_content"], encoding="utf-8")
    else:
        # Rebuild from fields
        existing = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        for key in ["display_name", "description", "scoped_skills", "input_schema", "output_schema", "max_iterations", "emit_plan_steps"]:
            if key in body:
                existing[key] = body[key]
        yaml_path.write_text(yaml.dump(existing, allow_unicode=True, sort_keys=False), encoding="utf-8")

    # Update system prompt if provided
    if "system_prompt" in body:
        prompts_dir = agents_dir / "prompts"
        prompt_file = prompts_dir / f"{name}.md"
        prompt_file.write_text(body["system_prompt"], encoding="utf-8")

    return web.json_response({"name": name, "restart_required": True})


async def handle_delete_agent(request: web.Request) -> web.Response:
    """DELETE /api/agents/{name} — Delete agent YAML + prompt file."""
    name = request.match_info["name"]
    err = _validate_name(name)
    if err:
        return err
    registry = request.app["agent_registry"]
    agents_dir: Path = request.app["agents_dir"]

    if name not in registry:
        return web.json_response({"error": f"Agent '{name}' not found"}, status=404)

    spec = registry.get(name)

    # Delete YAML file
    if spec.source_path and spec.source_path.is_file():
        spec.source_path.unlink()

    # Delete prompt file
    prompt_file = agents_dir / "prompts" / f"{name}.md"
    if prompt_file.is_file():
        prompt_file.unlink()

    return web.json_response({"deleted": name, "restart_required": True})


# ─── Skills ──────────────────────────────────────────────────────────


async def handle_list_skills(request: web.Request) -> web.Response:
    """GET /api/skills — List all registered skills."""
    skills_dirs: list[Path] = request.app["skills_dirs"]
    skills = []

    for skills_dir in skills_dirs:
        if not skills_dir.is_dir():
            continue
        for skill_path in sorted(skills_dir.iterdir()):
            if not skill_path.is_dir():
                continue
            skill_md = skill_path / "SKILL.md"
            if not skill_md.is_file():
                continue
            # Read first line as description
            content = skill_md.read_text(encoding="utf-8")
            first_line = content.strip().split("\n")[0].lstrip("# ").strip() if content.strip() else ""
            skills.append({
                "name": skill_path.name,
                "description": first_line,
                "path": str(skill_path),
                "source_dir": str(skills_dir),
            })

    return web.json_response({"skills": skills})


async def handle_get_skill(request: web.Request) -> web.Response:
    """GET /api/skills/{name} — Get skill SKILL.md content."""
    name = request.match_info["name"]
    err = _validate_name(name)
    if err:
        return err
    skills_dirs: list[Path] = request.app["skills_dirs"]

    for skills_dir in skills_dirs:
        skill_path = skills_dir / name
        skill_md = skill_path / "SKILL.md"
        if skill_md.is_file():
            content = skill_md.read_text(encoding="utf-8")
            return web.json_response({
                "name": name,
                "content": content,
                "path": str(skill_path),
            })

    return web.json_response({"error": f"Skill '{name}' not found"}, status=404)


async def handle_create_skill(request: web.Request) -> web.Response:
    """POST /api/skills — Create a new skill directory + SKILL.md."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    if "name" not in body or "content" not in body:
        return web.json_response({"error": "Missing 'name' and/or 'content' fields"}, status=400)

    name = body["name"]
    err = _validate_name(name)
    if err:
        return err
    # Write to first writable skills dir (workspace preferred)
    skills_dirs: list[Path] = request.app["skills_dirs"]
    if not skills_dirs:
        return web.json_response(
            {"error": "No skill directory configured on server"},
            status=500,
        )
    target_dir = skills_dirs[0]

    skill_path = target_dir / name
    if skill_path.exists():
        return web.json_response({"error": f"Skill '{name}' already exists"}, status=409)

    skill_path.mkdir(parents=True, exist_ok=True)
    skill_md = skill_path / "SKILL.md"
    skill_md.write_text(body["content"], encoding="utf-8")

    return web.json_response({
        "name": name,
        "path": str(skill_path),
        "restart_required": True,
    }, status=201)


async def handle_update_skill(request: web.Request) -> web.Response:
    """PUT /api/skills/{name} — Update skill SKILL.md content."""
    name = request.match_info["name"]
    err = _validate_name(name)
    if err:
        return err
    skills_dirs: list[Path] = request.app["skills_dirs"]

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    if "content" not in body:
        return web.json_response({"error": "Missing 'content' field"}, status=400)

    for skills_dir in skills_dirs:
        skill_path = skills_dir / name
        skill_md = skill_path / "SKILL.md"
        if skill_md.is_file():
            skill_md.write_text(body["content"], encoding="utf-8")
            return web.json_response({"name": name, "restart_required": True})

    return web.json_response({"error": f"Skill '{name}' not found"}, status=404)


async def handle_delete_skill(request: web.Request) -> web.Response:
    """DELETE /api/skills/{name} — Delete skill directory."""
    name = request.match_info["name"]
    err = _validate_name(name)
    if err:
        return err
    skills_dirs: list[Path] = request.app["skills_dirs"]

    for skills_dir in skills_dirs:
        skill_path = skills_dir / name
        if skill_path.is_dir():
            shutil.rmtree(skill_path)
            return web.json_response({"deleted": name, "restart_required": True})

    return web.json_response({"error": f"Skill '{name}' not found"}, status=404)


def register_agent_routes(app: web.Application) -> None:
    """Register all agent/skill CRUD routes on the app."""
    app.router.add_get("/api/agents", handle_list_agents)
    app.router.add_get("/api/agents/{name}", handle_get_agent)
    app.router.add_post("/api/agents", handle_create_agent)
    app.router.add_put("/api/agents/{name}", handle_update_agent)
    app.router.add_delete("/api/agents/{name}", handle_delete_agent)

    app.router.add_get("/api/skills", handle_list_skills)
    app.router.add_get("/api/skills/{name}", handle_get_skill)
    app.router.add_post("/api/skills", handle_create_skill)
    app.router.add_put("/api/skills/{name}", handle_update_skill)
    app.router.add_delete("/api/skills/{name}", handle_delete_skill)

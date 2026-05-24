"""create_agent tool — orchestrator-only entry point for spawning expert subagents.

This is the *single* tool the Orchestrator uses to launch an expert agent
(see decision D2/D6 in `.trellis/tasks/05-18-subagent-prompt-minimal-create-agent/prd.md`).

Strict invariants (fail-fast, no defaults, no silent fallbacks):
- ``name``  must be a registered expert agent.
- ``task``  must be a non-empty prompt within ``MAX_TASK_LEN``; the Orchestrator
            is expected to write the full prompt body — the subagent will NOT
            read ``spec.system_prompt`` nor receive an auto-injected blackboard
            snapshot.
- ``target`` must be set (asset / scope identifier — IP, CIDR, domain, URL, …).
            Used for routing/audit; **not** spliced into the LLM prompt by this
            tool. The Orchestrator is responsible for embedding any necessary
            target text into ``task`` itself.
- ``endpoint_url`` + ``endpoint_param`` are required *iff* the resolved spec has
            ``endpoint_bound=true``; they form the endpoint-level mutex key
            enforced by ``SubagentManager`` (see decision D5/D8).
"""

from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from secbot.agent.tools.base import Tool, tool_parameters
from secbot.agent.tools.schema import StringSchema, tool_parameters_schema

if TYPE_CHECKING:
    from secbot.agent.subagent import SubagentManager


# Hard upper bound on the ``task`` payload coming from the Orchestrator. The
# value is intentionally generous: a full prompt usually fits well under 8K
# chars, and 16K leaves head-room for embedded findings/blackboard excerpts
# the Orchestrator chooses to inline. Anything past this is almost certainly
# a bug (e.g. dumping a whole repo into the field).
MAX_TASK_LEN = 16_000

_PRESET_AGENT_ALIASES = {
    "recon": "asset_discovery",
    "crawl": "crawl_web",
    "triage": "vuln_scan",
    "report": "report",
}


def _normalise_budget_share(value: Any | None, defaults: dict[str, Any]) -> dict[str, Any]:
    if value is None:
        return dict(defaults)
    if not isinstance(value, dict):
        raise ValueError("budget_share must be an object")
    wall = value.get("max_wall_clock_sec", defaults["max_wall_clock_sec"])
    calls = value.get("max_tool_calls", defaults["max_tool_calls"])
    try:
        wall_f = float(wall)
        calls_i = int(calls)
    except (TypeError, ValueError) as exc:
        raise ValueError("budget_share values must be numeric") from exc
    if wall_f < 0 or calls_i < 0:
        raise ValueError("budget_share values must be non-negative")
    return {"max_wall_clock_sec": wall_f, "max_tool_calls": calls_i}


def _target_from_scope_view(scope_view: Any) -> str | None:
    if not isinstance(scope_view, dict):
        return None
    in_scope = scope_view.get("in_scope")
    if isinstance(in_scope, list):
        for item in in_scope:
            text = str(item).strip()
            if text:
                return text
    target = scope_view.get("target")
    return str(target).strip() if target else None


def _agent_for_preset(preset: str, registry: Any) -> str:
    name = preset.strip()
    if name.startswith("legacy:"):
        return name.split(":", 1)[1]
    if name in _PRESET_AGENT_ALIASES:
        return _PRESET_AGENT_ALIASES[name]
    if registry is not None and name in registry:
        return name
    return name


@tool_parameters(
    tool_parameters_schema(
        name=StringSchema(
            "Expert agent name. MUST be one of the agents listed in the "
            "orchestrator prompt (or /api/agents). Unknown names are rejected.",
        ),
        task=StringSchema(
            "Full prompt for the subagent. The Orchestrator writes the entire "
            "instruction body here — the subagent does NOT read any per-agent "
            f"system_prompt. Hard limit: {MAX_TASK_LEN} characters.",
        ),
        target=StringSchema(
            "Asset / scope identifier (IP, CIDR, domain, URL, …). Required for "
            "every call; used for routing & audit. Not auto-injected into the "
            "LLM prompt — restate it inside 'task' if the subagent needs it.",
        ),
        endpoint_url=StringSchema(
            "Endpoint URL. REQUIRED iff the target agent is endpoint_bound "
            "(e.g. vuln_detec / weak_password). Forms the endpoint mutex key "
            "together with endpoint_param.",
            nullable=True,
        ),
        endpoint_param=StringSchema(
            "Endpoint parameter name. REQUIRED iff the target agent is "
            "endpoint_bound. Forms the endpoint mutex key together with "
            "endpoint_url.",
            nullable=True,
        ),
        required=["name", "task", "target"],
    )
)
class SpawnTool(Tool):
    """Tool to create an expert subagent (orchestrator-only)."""

    def __init__(self, manager: "SubagentManager"):
        self._manager = manager
        self._origin_channel: ContextVar[str] = ContextVar("spawn_origin_channel", default="cli")
        self._origin_chat_id: ContextVar[str] = ContextVar("spawn_origin_chat_id", default="direct")
        self._session_key: ContextVar[str] = ContextVar("spawn_session_key", default="cli:direct")
        self._origin_message_id: ContextVar[str | None] = ContextVar(
            "spawn_origin_message_id",
            default=None,
        )

    def set_context(self, channel: str, chat_id: str, effective_key: str | None = None) -> None:
        """Set the origin context for subagent announcements."""
        self._origin_channel.set(channel)
        self._origin_chat_id.set(chat_id)
        self._session_key.set(effective_key or f"{channel}:{chat_id}")

    def set_origin_message_id(self, message_id: str | None) -> None:
        """Set the source message id for downstream deduplication."""
        self._origin_message_id.set(message_id)

    @property
    def name(self) -> str:
        return "create_agent"

    @property
    def description(self) -> str:
        return (
            "Create an expert subagent to run a concrete task. Provide the FULL "
            "prompt in 'task', the asset/scope in 'target', and — when the agent "
            "is endpoint-bound — both 'endpoint_url' and 'endpoint_param'. The "
            "orchestrator owns prompt composition; the subagent does not read "
            "per-agent system prompts and is not given an auto-injected "
            "blackboard snapshot."
        )

    async def execute(
        self,
        name: str | None = None,
        task: str | None = None,
        target: str | None = None,
        endpoint_url: str | None = None,
        endpoint_param: str | None = None,
        **kwargs: Any,
    ) -> str:
        """Validate the create_agent call (D6 strict / fail-fast) and spawn."""

        # ---- 1. Field presence & shape (no defaults, no silent fallback) ----
        if not isinstance(name, str) or not name.strip():
            return (
                "create_agent failed: 'name' is required and must be a "
                "non-empty string naming a registered expert agent."
            )
        if not isinstance(task, str) or not task.strip():
            return "create_agent failed: 'task' is required and must be non-empty."
        if not isinstance(target, str) or not target.strip():
            return (
                "create_agent failed: 'target' is required (asset/scope "
                "identifier such as IP, CIDR, domain or URL)."
            )
        if len(task) > MAX_TASK_LEN:
            return (
                f"create_agent failed: 'task' length {len(task)} exceeds the "
                f"maximum of {MAX_TASK_LEN} characters. Split the work or "
                "summarise before delegating."
            )

        name = name.strip()
        target = target.strip()

        # ---- 2. Agent registry lookup ----------------------------------------
        registry = getattr(self._manager, "agent_registry", None)
        if registry is None:
            return (
                "create_agent failed: no agent registry is attached to the "
                "SubagentManager (server mis-configuration)."
            )
        if name not in registry:
            available = ", ".join(registry.names()) or "<none registered>"
            return (
                f"create_agent failed: unknown agent '{name}'. "
                f"Available agents: {available}."
            )
        spec = registry.get(name)
        if not spec.available:
            missing = ", ".join(spec.missing_binaries) or "<unknown>"
            return (
                f"create_agent failed: agent '{name}' is offline (missing "
                f"binaries: {missing}). Install them and retry."
            )

        # ---- 3. Endpoint-bound enforcement (D5/D8) --------------------------
        if spec.endpoint_bound:
            if not isinstance(endpoint_url, str) or not endpoint_url.strip():
                return (
                    f"create_agent failed: agent '{name}' is endpoint-bound; "
                    "'endpoint_url' is required."
                )
            if not isinstance(endpoint_param, str) or not endpoint_param.strip():
                return (
                    f"create_agent failed: agent '{name}' is endpoint-bound; "
                    "'endpoint_param' is required."
                )
            endpoint_url = endpoint_url.strip()
            endpoint_param = endpoint_param.strip()
        else:
            # Non-endpoint agents must not receive endpoint fields — reject so
            # the orchestrator's intent stays unambiguous.
            if endpoint_url is not None or endpoint_param is not None:
                return (
                    f"create_agent failed: agent '{name}' is not endpoint-bound; "
                    "omit 'endpoint_url' and 'endpoint_param'."
                )

        # ---- 4. Concurrency guard (existing behaviour) ----------------------
        running = self._manager.get_running_count()
        limit = self._manager.max_concurrent_subagents
        if running >= limit:
            return (
                f"Cannot spawn subagent: concurrency limit reached "
                f"({running}/{limit} running). Wait for a running subagent "
                f"to complete before spawning a new one."
            )

        # ---- 5. Hand off to the manager -------------------------------------
        return await self._manager.spawn(
            task=task,
            label=None,
            agent=name,
            target=target,
            endpoint_url=endpoint_url,
            endpoint_param=endpoint_param,
            origin_channel=self._origin_channel.get(),
            origin_chat_id=self._origin_chat_id.get(),
            session_key=self._session_key.get(),
            origin_message_id=self._origin_message_id.get(),
        )


class CreateWorkerTool(SpawnTool):
    """Pi create_worker tool with a legacy-agent bridge."""

    def __init__(self, manager: "SubagentManager"):
        super().__init__(manager)
        self._budget_defaults: ContextVar[dict[str, Any]] = ContextVar(
            "worker_budget_defaults",
            default={"max_wall_clock_sec": 300.0, "max_tool_calls": 15},
        )

    def set_budget_defaults(self, *, max_wall_clock_sec: float, max_tool_calls: int) -> None:
        self._budget_defaults.set(
            {
                "max_wall_clock_sec": float(max_wall_clock_sec),
                "max_tool_calls": int(max_tool_calls),
            }
        )

    @property
    def name(self) -> str:
        return "create_worker"

    @property
    def description(self) -> str:
        return (
            "Create a limited worker from a Pi worker preset. Provide preset, full "
            "task prompt, scope_view, and budget_share. Presets recon/crawl/triage/"
            "report are bridged to existing expert agents; legacy:<old_name> keeps "
            "backward compatibility."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "preset": {
                    "type": "string",
                    "description": "Worker preset such as recon, crawl, triage, report, or legacy:<agent>.",
                },
                "task": {
                    "type": "string",
                    "description": f"Full worker prompt. Hard limit: {MAX_TASK_LEN} characters.",
                },
                "scope_view": {
                    "type": "object",
                    "properties": {
                        "in_scope": {"type": "array", "items": {"type": "string"}},
                        "out_of_scope": {"type": "array", "items": {"type": "string"}},
                        "target": {"type": "string"},
                    },
                    "additionalProperties": True,
                },
                "budget_share": {
                    "type": "object",
                    "properties": {
                        "max_wall_clock_sec": {"type": "number", "minimum": 0},
                        "max_tool_calls": {"type": "integer", "minimum": 0},
                    },
                    "additionalProperties": False,
                },
                "skills_subset": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional subset of the preset skills.",
                },
                "endpoint_url": {"type": ["string", "null"]},
                "endpoint_param": {"type": ["string", "null"]},
            },
            "required": ["preset", "task", "scope_view"],
        }

    async def execute(
        self,
        preset: str | None = None,
        task: str | None = None,
        scope_view: dict[str, Any] | None = None,
        budget_share: dict[str, Any] | None = None,
        skills_subset: list[str] | None = None,
        endpoint_url: str | None = None,
        endpoint_param: str | None = None,
        **kwargs: Any,
    ) -> str:
        if not isinstance(preset, str) or not preset.strip():
            return "create_worker failed: 'preset' is required and must be non-empty."
        if not isinstance(task, str) or not task.strip():
            return "create_worker failed: 'task' is required and must be non-empty."
        if len(task) > MAX_TASK_LEN:
            return (
                f"create_worker failed: 'task' length {len(task)} exceeds the "
                f"maximum of {MAX_TASK_LEN} characters."
            )
        target = kwargs.get("target")
        if not isinstance(target, str) or not target.strip():
            target = _target_from_scope_view(scope_view)
        if not isinstance(target, str) or not target.strip():
            return "create_worker failed: scope_view.in_scope must include at least one target."
        if skills_subset is not None and (
            not isinstance(skills_subset, list)
            or any(not isinstance(item, str) or not item.strip() for item in skills_subset)
        ):
            return "create_worker failed: skills_subset must be a list of non-empty strings."
        try:
            share = _normalise_budget_share(budget_share, self._budget_defaults.get())
        except ValueError as exc:
            return f"create_worker failed: {exc}"

        registry = getattr(self._manager, "agent_registry", None)
        name = _agent_for_preset(preset, registry)
        if registry is None:
            return (
                "create_worker failed: no agent registry is attached to the "
                "SubagentManager (server mis-configuration)."
            )
        if name not in registry:
            available = ", ".join(registry.names()) or "<none registered>"
            return (
                f"create_worker failed: unknown preset '{preset}'. "
                f"Available legacy agents: {available}."
            )
        spec = registry.get(name)
        if not spec.available:
            missing = ", ".join(spec.missing_binaries) or "<unknown>"
            return (
                f"create_worker failed: preset '{preset}' is offline (missing "
                f"binaries: {missing}). Install them and retry."
            )
        if spec.endpoint_bound:
            if not isinstance(endpoint_url, str) or not endpoint_url.strip():
                return (
                    f"create_worker failed: preset '{preset}' is endpoint-bound; "
                    "'endpoint_url' is required."
                )
            if not isinstance(endpoint_param, str) or not endpoint_param.strip():
                return (
                    f"create_worker failed: preset '{preset}' is endpoint-bound; "
                    "'endpoint_param' is required."
                )
            endpoint_url = endpoint_url.strip()
            endpoint_param = endpoint_param.strip()
        elif endpoint_url is not None or endpoint_param is not None:
            return (
                f"create_worker failed: preset '{preset}' is not endpoint-bound; "
                "omit 'endpoint_url' and 'endpoint_param'."
            )

        running = self._manager.get_running_count()
        limit = self._manager.max_concurrent_subagents
        if running >= limit:
            return (
                f"Cannot spawn worker: concurrency limit reached "
                f"({running}/{limit} running). Wait for a running worker "
                "to complete before spawning a new one."
            )

        return await self._manager.spawn(
            task=task,
            label=None,
            agent=name,
            target=target.strip(),
            endpoint_url=endpoint_url,
            endpoint_param=endpoint_param,
            origin_channel=self._origin_channel.get(),
            origin_chat_id=self._origin_chat_id.get(),
            session_key=self._session_key.get(),
            origin_message_id=self._origin_message_id.get(),
            budget_share=share,
            skills_subset=skills_subset,
        )

"""create_agent tool — orchestrator-only entry point for spawning expert subagents.

This is the *single* tool the Orchestrator uses to launch an expert agent
(see decision D2/D6 in `.trellis/tasks/05-18-subagent-prompt-minimal-create-agent/prd.md`).

Strict invariants (fail-fast, no defaults, no silent fallbacks):
- ``name``  must be a registered expert agent.
- ``task``  must be a non-empty concrete task within ``MAX_TASK_LEN``; the
            platform prepends the project-authored expert execution contract
            from ``spec.system_prompt`` to the subagent's initial user message,
            but no blackboard snapshot is auto-injected.
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
# value is intentionally generous: a concrete task body usually fits well under
# 8K chars, and 16K leaves head-room for embedded findings/blackboard excerpts
# the Orchestrator chooses to inline. Anything past this is almost certainly a
# bug (e.g. dumping a whole repo into the field).
MAX_TASK_LEN = 16_000


@tool_parameters(
    tool_parameters_schema(
        name=StringSchema(
            "Expert agent name. MUST be one of the agents listed in the "
            "orchestrator prompt (or /api/agents). Unknown names are rejected.",
        ),
        task=StringSchema(
            "Concrete task body for the subagent. The platform prepends the "
            "registered expert execution contract to the initial user message; "
            "the Orchestrator must still include goal, scope, relevant findings, "
            f"constraints, and expected output here. Hard limit: {MAX_TASK_LEN} "
            "characters.",
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
            "Create an expert subagent to run a concrete task. Provide the "
            "task body in 'task', the asset/scope in 'target', and — when the "
            "agent is endpoint-bound — both 'endpoint_url' and 'endpoint_param'. The "
            "platform prepends the project-authored expert execution contract "
            "to the subagent's user message, but no blackboard snapshot is "
            "auto-injected."
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

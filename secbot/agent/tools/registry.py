"""Tool registry for dynamic tool management."""

import asyncio
from dataclasses import replace
from typing import Any

from secbot.agent.tools.base import Tool
from secbot.policy import Action, PolicyContext, PolicyEngine
from secbot.policy.engine import policy_denied_payload, user_denied_payload


class ToolRegistry:
    """
    Registry for agent tools.

    Allows dynamic registration and execution of tools.
    """

    def __init__(
        self,
        *,
        policy: PolicyEngine | None = None,
        policy_context: PolicyContext | None = None,
    ):
        self._tools: dict[str, Tool] = {}
        self._cached_definitions: list[dict[str, Any]] | None = None
        self.policy = policy or PolicyEngine()
        self.policy_context = policy_context or PolicyContext()

    def set_policy_context(self, context: PolicyContext) -> None:
        """Replace per-run policy context used by future tool executions."""
        self.policy_context = context

    def register(self, tool: Tool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool
        self._cached_definitions = None

    def unregister(self, name: str) -> None:
        """Unregister a tool by name."""
        self._tools.pop(name, None)
        self._cached_definitions = None

    def get(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    @staticmethod
    def _schema_name(schema: dict[str, Any]) -> str:
        """Extract a normalized tool name from either OpenAI or flat schemas."""
        fn = schema.get("function")
        if isinstance(fn, dict):
            name = fn.get("name")
            if isinstance(name, str):
                return name
        name = schema.get("name")
        return name if isinstance(name, str) else ""

    def get_definitions(self) -> list[dict[str, Any]]:
        """Get tool definitions with stable ordering for cache-friendly prompts.

        Built-in tools are sorted first as a stable prefix, then MCP tools are
        sorted and appended.  The result is cached until the next
        register/unregister call.
        """
        if self._cached_definitions is not None:
            return self._cached_definitions

        definitions = [tool.to_schema() for tool in self._tools.values()]
        builtins: list[dict[str, Any]] = []
        mcp_tools: list[dict[str, Any]] = []
        for schema in definitions:
            name = self._schema_name(schema)
            if name.startswith("mcp_"):
                mcp_tools.append(schema)
            else:
                builtins.append(schema)

        builtins.sort(key=self._schema_name)
        mcp_tools.sort(key=self._schema_name)
        self._cached_definitions = builtins + mcp_tools
        return self._cached_definitions

    def prepare_call(
        self,
        name: str,
        params: dict[str, Any],
    ) -> tuple[Tool | None, dict[str, Any], str | None]:
        """Resolve, cast, and validate one tool call."""
        # Guard against invalid parameter types (e.g., list instead of dict)
        if not isinstance(params, dict) and name in ('write_file', 'read_file'):
            return None, params, (
                f"Error: Tool '{name}' parameters must be a JSON object, got {type(params).__name__}. "
                "Use named parameters: tool_name(param1=\"value1\", param2=\"value2\")"
            )

        tool = self._tools.get(name)
        if not tool:
            return None, params, (
                f"Error: Tool '{name}' not found. Available: {', '.join(self.tool_names)}"
            )

        cast_params = tool.cast_params(params)
        errors = tool.validate_params(cast_params)
        if errors:
            return tool, cast_params, (
                f"Error: Invalid parameters for tool '{name}': " + "; ".join(errors)
            )
        return tool, cast_params, None

    async def execute_prepared(
        self,
        name: str,
        tool: Tool,
        params: dict[str, Any],
    ) -> Any:
        """Policy-check and execute an already prepared tool call."""
        action = self._action_for(tool)
        skill_meta = getattr(tool, "metadata", None)
        policy_ctx = self.policy.with_context(
            self.policy_context,
            skill_metadata=skill_meta,
        )
        approved = getattr(tool, "is_policy_approved", None)
        if skill_meta is not None and callable(approved) and approved():
            policy_ctx = replace(
                policy_ctx,
                approved_skills=frozenset(
                    set(policy_ctx.approved_skills) | {skill_meta.name}
                ),
            )
        decision = await self.policy.check(action, params, policy_ctx)

        if decision.verdict == "deny":
            return policy_denied_payload(decision)

        if decision.verdict == "need_approval":
            request_recorder = getattr(tool, "record_policy_request", None)
            approval_payload = decision.approval_payload
            if approval_payload is not None and callable(request_recorder):
                approval_payload = request_recorder(
                    params,
                    policy_ctx.scan_id,
                    decision.approval_payload,
                )
            if policy_ctx.confirm is None or approval_payload is None:
                denied_recorder = getattr(tool, "record_policy_denied", None)
                if callable(denied_recorder):
                    denied_recorder(policy_ctx.scan_id, timeout=False)
                return user_denied_payload(decision)
            timeout_sec = self._approval_timeout_for(tool)
            try:
                approved_by_user = await asyncio.wait_for(
                    policy_ctx.confirm(approval_payload),
                    timeout=timeout_sec,
                )
            except asyncio.TimeoutError:
                denied_recorder = getattr(tool, "record_policy_denied", None)
                if callable(denied_recorder):
                    denied_recorder(policy_ctx.scan_id, timeout=True)
                return user_denied_payload(
                    replace(decision, reason="confirm_timeout")
                )
            if not approved_by_user:
                denied_recorder = getattr(tool, "record_policy_denied", None)
                if callable(denied_recorder):
                    denied_recorder(policy_ctx.scan_id, timeout=False)
                return user_denied_payload(decision)
            mark_approved = getattr(tool, "mark_policy_approved", None)
            if callable(mark_approved):
                mark_approved(params, policy_ctx.scan_id, approval_payload)

        return await tool.execute(**params)

    @staticmethod
    def _approval_timeout_for(tool: Tool) -> float | None:
        timeout_getter = getattr(tool, "policy_approval_timeout_sec", None)
        if not callable(timeout_getter):
            return None
        timeout = timeout_getter()
        if isinstance(timeout, int | float):
            return max(0.0, float(timeout))
        return None

    async def execute(self, name: str, params: dict[str, Any]) -> Any:
        """Execute a tool by name with given parameters."""
        hint = "\n\n[Analyze the error above and try a different approach.]"
        tool, params, error = self.prepare_call(name, params)
        if error:
            return error + hint

        try:
            assert tool is not None  # guarded by prepare_call()
            result = await self.execute_prepared(name, tool, params)
            if isinstance(result, str) and result.startswith("Error"):
                return result + hint
            return result
        except Exception as e:
            return f"Error executing {name}: {str(e)}" + hint

    @staticmethod
    def _action_for(tool: Tool) -> Action:
        name = tool.name
        if name in {"report-html", "report-markdown", "report-docx", "report-pdf"}:
            return "report.publish"
        if getattr(tool, "metadata", None) is not None:
            return "skill.invoke"
        if name == "create_agent":
            return "worker.spawn"
        if name == "blackboard_write":
            return "blackboard.write"
        if name == "exec":
            return "exec.shell"
        if name in {"curl", "web_fetch"}:
            return "http.fetch"
        if name in {"read_file", "list_dir", "glob", "grep"}:
            return "fs.read"
        if name in {"write_file", "edit_file", "notebook_edit"}:
            return "fs.write"
        if name == "request_approval":
            return "approval.request"
        return "tool.invoke"

    @property
    def tool_names(self) -> list[str]:
        """Get list of registered tool names."""
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

"""``kind=tool`` executor — delegate to the global ToolRegistry.

Contract:

* ``step.ref`` is the tool name (must exist in the registry at run
  time — otherwise ``workflow.executor.tool_not_found``).
* ``args`` is forwarded verbatim to ``ToolRegistry.execute``.
* The tool's return value becomes ``output``. If the tool returns a
  string that begins with ``"Error"`` (the registry's sentinel for
  validation / execution failures), this executor treats it as a
  failure and raises :class:`ExecutorError`. Non-string returns are
  passed through untouched.
"""

from __future__ import annotations

from typing import Any

from secbot.workflow.executors.base import ExecutorError, StepContext, StepExecutor
from secbot.workflow.types import WorkflowStep


class ToolExecutor(StepExecutor):
    """Adapt ``ToolRegistry.execute`` to the workflow step contract."""

    kind = "tool"

    def __init__(self, tool_registry: Any) -> None:
        if tool_registry is None:
            raise ValueError("ToolExecutor requires a non-None tool_registry")
        self._tools = tool_registry

    async def _run(
        self,
        step: WorkflowStep,
        args: dict[str, Any],
        ctx: StepContext,
    ) -> Any:
        name = step.ref
        if not name:
            raise ExecutorError("workflow.validation.ref_required: step.ref is empty")
        if not self._tools.has(name):
            raise ExecutorError(f"workflow.executor.tool_not_found: {name}")

        result = await self._tools.execute(name, args)

        # The registry returns a string starting with "Error" for any
        # validation / execution failure (see
        # ``secbot/agent/tools/registry.py::execute``). We surface that
        # verbatim so the user sees the original message but classify
        # it as a step failure so ``on_error`` / retry can kick in.
        if isinstance(result, str) and result.startswith("Error"):
            raise ExecutorError(result)

        return result

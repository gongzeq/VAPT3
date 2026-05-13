"""Step executors for the workflow engine.

Every executor accepts interpolated ``args`` and a ``StepContext`` and
returns a :class:`secbot.workflow.types.StepResult`. The base class owns
timing + error wrapping; subclasses only implement ``_run`` and return
the raw output (or raise).

Public surface:

* :class:`StepExecutor` — abstract base
* :class:`StepContext` — data passed to every executor
* :class:`ExecutorError` — standard wrapper for user-facing failures
* concrete executors: :mod:`.tool`, :mod:`.script`, :mod:`.agent`,
  :mod:`.llm`
* :func:`build_default_executors` — assembles the default mapping

Spec: ``.trellis/tasks/05-11-workflow-builder-ui/api-spec.md`` §3.
"""

from __future__ import annotations

from secbot.workflow.executors.base import (
    ExecutorError,
    StepContext,
    StepExecutor,
)

__all__ = [
    "ExecutorError",
    "StepContext",
    "StepExecutor",
    "build_default_executors",
]


def build_default_executors(
    *,
    tool_registry,
    agent_registry=None,
    llm_provider=None,
) -> dict[str, StepExecutor]:
    """Assemble the standard {kind → executor} mapping for the runner.

    Any dependency can be omitted — the corresponding kind will then
    return a structured ``workflow.executor.*`` error when invoked. This
    keeps unit tests cheap (tool-only workflows don't need an LLM).
    """
    from secbot.workflow.executors.agent import AgentExecutor
    from secbot.workflow.executors.llm import LlmExecutor
    from secbot.workflow.executors.script import ScriptExecutor
    from secbot.workflow.executors.tool import ToolExecutor

    return {
        "tool": ToolExecutor(tool_registry),
        "script": ScriptExecutor(tool_registry),
        "agent": AgentExecutor(agent_registry=agent_registry, llm_provider=llm_provider),
        "llm": LlmExecutor(llm_provider=llm_provider),
    }

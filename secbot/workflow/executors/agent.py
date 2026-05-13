"""``kind=agent`` executor — invoke a registered expert agent.

Expert agents are YAML-defined (:mod:`secbot.agents.registry`). Each
spec carries:

* ``system_prompt``  (raw string)
* ``input_schema``   (JSON Schema 2020-12 describing ``args``)
* ``output_schema``  (JSON Schema describing the expected JSON result)
* ``model`` (optional override — ignored in PR1; the global provider
  is used so ops can cap cost centrally, see dev-guide §6)

For PR1 we intentionally ship a **minimal direct-LLM driver** rather
than the full orchestrator tool-call loop. The executor:

1. Resolves the agent from ``agent_registry.get(step.ref)``.
2. Validates ``args`` against ``input_schema`` (``jsonschema`` is
   already a hard dep of the registry; same library gives us runtime
   validation for free).
3. Calls ``provider.chat`` with::

       [{"role": "system", "content": spec.system_prompt},
        {"role": "user",   "content": json.dumps(args)}]

4. Parses the content as JSON and validates it against
   ``output_schema``.

Output payload matches the agent's ``output_schema`` verbatim. This is
enough for bench-marking and the mocked end-to-end tests; the full
tool-loop path is a follow-up PR (tracked in dev-guide §7 TODOs).
"""

from __future__ import annotations

import json
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from secbot.workflow.executors.base import ExecutorError, StepContext, StepExecutor
from secbot.workflow.types import WorkflowStep


class AgentExecutor(StepExecutor):
    """Resolve + run an expert-agent YAML spec with strict schema checks."""

    kind = "agent"

    def __init__(
        self,
        *,
        agent_registry: Any = None,
        llm_provider: Any = None,
    ) -> None:
        self._registry = agent_registry
        self._provider = llm_provider

    async def _run(
        self,
        step: WorkflowStep,
        args: dict[str, Any],
        ctx: StepContext,
    ) -> Any:
        if self._registry is None:
            raise ExecutorError(
                "workflow.validation.agent_config: no agent registry is configured"
            )
        if self._provider is None:
            raise ExecutorError(
                "workflow.validation.llm_config: no LLM provider is configured"
            )

        name = step.ref
        if not name:
            raise ExecutorError("workflow.validation.ref_required: step.ref is empty")

        spec = _resolve_agent(self._registry, name)

        # Validate args against the agent's input schema. Registry entries
        # were pre-checked as valid JSON Schema 2020-12 at load time, so
        # Draft202012Validator here can only raise on *data* errors.
        try:
            Draft202012Validator(dict(spec.input_schema)).validate(args)
        except ValidationError as exc:
            raise ExecutorError(
                f"workflow.validation.agent_args: {exc.message}"
            ) from exc

        messages = [
            {"role": "system", "content": spec.system_prompt},
            {"role": "user", "content": json.dumps(args, ensure_ascii=False)},
        ]

        try:
            resp = await self._provider.chat(
                messages,
                max_tokens=4096,
                temperature=0.2,
            )
        except Exception as exc:
            raise ExecutorError(
                f"workflow.executor.agent_failed: {exc}"
            ) from exc

        if getattr(resp, "finish_reason", "stop") == "error":
            err_msg = (
                getattr(resp, "error_type", None)
                or getattr(resp, "error_code", None)
                or "unknown"
            )
            raise ExecutorError(f"workflow.executor.agent_failed: {err_msg}")

        content = getattr(resp, "content", None)
        if not isinstance(content, str) or not content.strip():
            raise ExecutorError(
                "workflow.executor.agent_empty: agent returned no content"
            )

        parsed = _parse_json_payload(content)

        try:
            Draft202012Validator(dict(spec.output_schema)).validate(parsed)
        except ValidationError as exc:
            raise ExecutorError(
                f"workflow.executor.agent_output_schema: {exc.message}"
            ) from exc

        return parsed


def _resolve_agent(registry: Any, name: str) -> Any:
    """``agent_registry.get`` in the shipped registry raises for unknown
    names; tolerate dict-like mocks used in tests too."""
    try:
        spec = registry.get(name)
    except Exception as exc:
        raise ExecutorError(f"workflow.executor.agent_not_found: {name}") from exc
    if spec is None:
        raise ExecutorError(f"workflow.executor.agent_not_found: {name}")
    return spec


def _parse_json_payload(content: str) -> Any:
    """Accept either a raw JSON document or a fenced ```json``` block."""
    text = content.strip()
    if text.startswith("```"):
        # Strip optional ```json … ``` fences that some providers wrap
        # structured output in.
        newline = text.find("\n")
        if newline != -1:
            text = text[newline + 1 :]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ExecutorError(
            f"workflow.executor.agent_parse: invalid JSON ({exc.msg})"
        ) from exc

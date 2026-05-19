"""``kind=llm`` executor — direct chat completion via the global provider.

Per dev-guide §1 the provider is fixed at the process level (global
config). The user picks prompts, temperature, maxTokens, and optional
``responseFormat="json"``. No tool-calling loop here — that's the
:mod:`.agent` executor's job.

Args contract (camelCase on the wire; the runner has already
interpolated ``${…}`` placeholders before we see them)::

    {
        "systemPrompt": "…",    # optional
        "userPrompt":   "…",    # required
        "temperature":  0.7,    # optional, 0.0..2.0
        "maxTokens":    800,    # optional, ≥ 1
        "responseFormat": "json" | "text"  # optional, defaults to "text"
    }

Output payload::

    {
        "content":      <str | None>,
        "finishReason": <str>,
        "usage":        {"promptTokens": n, "completionTokens": n},
        "parsed":       <any>        # only present when responseFormat="json"
    }
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from secbot.workflow.executors.base import ExecutorError, StepContext, StepExecutor
from secbot.workflow.types import WorkflowStep

logger = logging.getLogger(__name__)

_DEFAULT_MAX_TOKENS = 4096
_DEFAULT_TEMPERATURE = 0.7


class LlmExecutor(StepExecutor):
    """One-shot LLM chat call using the default provider.

    Hot-reload contract
    -------------------
    The provider can be supplied two ways:

    * ``llm_provider`` — a fixed instance (legacy / tests).
    * ``provider_loader`` — a zero-arg callable returning the *current*
      provider. Called at the start of every ``_run`` so that config
      changes (e.g. a new apiKey saved via the WebUI settings page) are
      picked up without restarting the gateway, mirroring the AgentLoop
      behaviour (see ``secbot/agent/loop.py::_refresh_provider_snapshot``).

    When both are provided, ``provider_loader`` wins; on loader failure
    the cached ``llm_provider`` is used as a fallback so a transient
    config-read error never breaks an in-flight workflow.
    """

    kind = "llm"

    def __init__(
        self,
        *,
        llm_provider: Any = None,
        provider_loader: Callable[[], Any] | None = None,
    ) -> None:
        # ``None`` is allowed so unit tests without an LLM wire can still
        # construct the executor table; the failure surfaces only when a
        # step tries to run.
        self._provider = llm_provider
        self._provider_loader = provider_loader

    def _resolve_provider(self) -> Any:
        """Return the freshest provider; fall back to the cached one on error."""
        if self._provider_loader is not None:
            try:
                fresh = self._provider_loader()
            except Exception:
                logger.warning(
                    "workflow.llm: provider_loader failed; falling back to cached provider",
                    exc_info=True,
                )
            else:
                if fresh is not None:
                    return fresh
        return self._provider

    async def _run(
        self,
        step: WorkflowStep,
        args: dict[str, Any],
        ctx: StepContext,
    ) -> Any:
        provider = self._resolve_provider()
        if provider is None:
            raise ExecutorError(
                "workflow.validation.llm_config: no LLM provider is configured"
            )

        system_prompt = args.get("systemPrompt") or args.get("system_prompt")
        user_prompt = args.get("userPrompt") or args.get("user_prompt")
        if not isinstance(user_prompt, str) or not user_prompt.strip():
            raise ExecutorError(
                "workflow.validation.llm_prompt: args.userPrompt is required"
            )
        if system_prompt is not None and not isinstance(system_prompt, str):
            raise ExecutorError(
                "workflow.validation.llm_prompt: args.systemPrompt must be a string"
            )

        temperature = args.get("temperature", _DEFAULT_TEMPERATURE)
        max_tokens = args.get("maxTokens", args.get("max_tokens", _DEFAULT_MAX_TOKENS))
        response_format = args.get("responseFormat", args.get("response_format", "text"))

        if not isinstance(temperature, (int, float)) or not (0.0 <= float(temperature) <= 2.0):
            raise ExecutorError(
                "workflow.validation.llm_temperature: temperature must be a number in [0, 2]"
            )
        if not isinstance(max_tokens, int) or max_tokens < 1:
            raise ExecutorError(
                "workflow.validation.llm_max_tokens: maxTokens must be a positive int"
            )
        if response_format not in ("text", "json"):
            raise ExecutorError(
                "workflow.validation.llm_response_format: "
                "responseFormat must be 'text' or 'json'"
            )

        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        try:
            resp = await provider.chat(
                messages,
                max_tokens=int(max_tokens),
                temperature=float(temperature),
            )
        except Exception as exc:
            raise ExecutorError(
                f"workflow.executor.llm_failed: {exc}"
            ) from exc

        if getattr(resp, "finish_reason", "stop") == "error":
            err_msg = (
                getattr(resp, "error_type", None)
                or getattr(resp, "error_code", None)
                or "unknown"
            )
            raise ExecutorError(f"workflow.executor.llm_failed: {err_msg}")

        content = getattr(resp, "content", None)
        finish_reason = getattr(resp, "finish_reason", "stop")
        # ``length`` means the model ran out of budget before producing
        # any visible content — most commonly hit by reasoning models
        # that spend the whole ``maxTokens`` on hidden chain-of-thought.
        # Surface as a real failure so the step doesn't report "ok" with
        # an empty payload (task 05-11-workflow-builder-ui / 2026-05-13).
        if finish_reason == "length" and not (
            isinstance(content, str) and content.strip()
        ):
            raise ExecutorError(
                "workflow.executor.llm_truncated: "
                f"content empty at finishReason=length "
                f"(maxTokens={int(max_tokens)}) — increase maxTokens or "
                "switch to a non-reasoning model"
            )
        if finish_reason == "content_filter":
            raise ExecutorError(
                "workflow.executor.llm_blocked: response filtered by provider"
            )

        output: dict[str, Any] = {
            "content": content,
            "finishReason": finish_reason,
            "usage": {
                "promptTokens": int(resp.usage.get("prompt_tokens", 0))
                if getattr(resp, "usage", None) else 0,
                "completionTokens": int(resp.usage.get("completion_tokens", 0))
                if getattr(resp, "usage", None) else 0,
            },
        }

        if response_format == "json":
            if not isinstance(content, str) or not content.strip():
                raise ExecutorError(
                    "workflow.executor.llm_empty: responseFormat=json but content is empty"
                )
            try:
                output["parsed"] = json.loads(content)
            except json.JSONDecodeError as exc:
                raise ExecutorError(
                    f"workflow.executor.llm_parse: invalid JSON ({exc.msg})"
                ) from exc

        return output

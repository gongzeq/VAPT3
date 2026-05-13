"""Tests for the concrete :mod:`secbot.workflow.executors`.

Each executor is exercised against a minimal fake dependency (tool
registry / agent registry / LLM provider) so we cover the contract
*without* booting the real agent runtime.
"""

from __future__ import annotations

from typing import Any

import pytest

from secbot.workflow.executors import (
    StepContext,
    build_default_executors,
)
from secbot.workflow.executors.agent import AgentExecutor
from secbot.workflow.executors.llm import LlmExecutor
from secbot.workflow.executors.script import ScriptExecutor, _parse_exec_output
from secbot.workflow.executors.tool import ToolExecutor
from secbot.workflow.types import WorkflowStep


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FakeToolRegistry:
    def __init__(self, handlers: dict[str, Any] | None = None) -> None:
        self._handlers: dict[str, Any] = handlers or {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def has(self, name: str) -> bool:
        return name in self._handlers

    async def execute(self, name: str, params: dict[str, Any]) -> Any:
        self.calls.append((name, params))
        handler = self._handlers[name]
        if callable(handler):
            out = handler(params)
            if hasattr(out, "__await__"):
                return await out
            return out
        return handler


class FakeLLMResponse:
    def __init__(
        self,
        content: str | None,
        *,
        finish_reason: str = "stop",
        usage: dict[str, int] | None = None,
        error_type: str | None = None,
    ) -> None:
        self.content = content
        self.finish_reason = finish_reason
        self.usage = usage or {"prompt_tokens": 5, "completion_tokens": 7}
        self.error_type = error_type
        self.error_code = None


class FakeProvider:
    def __init__(self, response: FakeLLMResponse) -> None:
        self._response = response
        self.last_call: dict[str, Any] | None = None

    async def chat(self, messages, **kwargs):  # noqa: ANN001 — tolerate **kwargs
        self.last_call = {"messages": messages, "kwargs": kwargs}
        return self._response


def _step(kind: str, ref: str = "", args: dict[str, Any] | None = None) -> WorkflowStep:
    return WorkflowStep(id="s1", name=f"test-{kind}", kind=kind, ref=ref, args=args or {})


def _ctx() -> StepContext:
    return StepContext(inputs={}, steps={}, env={}, run_id="run_test")


# ---------------------------------------------------------------------------
# ToolExecutor
# ---------------------------------------------------------------------------


async def test_tool_executor_success_returns_raw_value():
    tr = FakeToolRegistry({"ping": {"pong": True}})
    execu = ToolExecutor(tr)
    result = await execu.execute(_step("tool", "ping"), {"x": 1}, _ctx())
    assert result.status == "ok"
    assert result.output == {"pong": True}
    assert tr.calls == [("ping", {"x": 1})]


async def test_tool_executor_missing_tool_errors():
    execu = ToolExecutor(FakeToolRegistry())
    result = await execu.execute(_step("tool", "absent"), {}, _ctx())
    assert result.status == "error"
    assert result.error is not None
    assert "tool_not_found" in result.error


async def test_tool_executor_error_sentinel_is_failure():
    tr = FakeToolRegistry({"bad": "Error: bad params"})
    execu = ToolExecutor(tr)
    result = await execu.execute(_step("tool", "bad"), {}, _ctx())
    assert result.status == "error"
    assert "bad params" in (result.error or "")


async def test_tool_executor_empty_ref_errors():
    execu = ToolExecutor(FakeToolRegistry())
    result = await execu.execute(_step("tool", ""), {}, _ctx())
    assert result.status == "error"
    assert "ref_required" in (result.error or "")


# ---------------------------------------------------------------------------
# ScriptExecutor
# ---------------------------------------------------------------------------


async def test_script_executor_shell_wraps_via_exec_tool():
    def exec_handler(params: dict[str, Any]) -> str:
        # Assert we wrap with bash -lc for shell kind.
        assert "bash -lc" in params["command"]
        return "hello\n\nExit code: 0"

    tr = FakeToolRegistry({"exec": exec_handler})
    execu = ScriptExecutor(tr)
    step = _step("script")
    result = await execu.execute(
        step,
        {"kind": "shell", "code": "echo hello", "timeoutMs": 1000},
        _ctx(),
    )
    assert result.status == "ok"
    assert result.output["exit_code"] == 0
    assert result.output["stdout"] == "hello"


async def test_script_executor_python_pipes_source_to_stdin():
    def exec_handler(params: dict[str, Any]) -> str:
        assert "python3 -" in params["command"]
        return "42\n\nExit code: 0"

    tr = FakeToolRegistry({"exec": exec_handler})
    execu = ScriptExecutor(tr)
    step = _step("script")
    result = await execu.execute(
        step,
        {"kind": "python", "code": "print(42)", "timeoutMs": 500},
        _ctx(),
    )
    assert result.status == "ok"
    assert result.output["stdout"] == "42"


async def test_script_executor_nonzero_exit_is_failure():
    def exec_handler(params: dict[str, Any]) -> str:  # noqa: ARG001
        return "oops\n\nSTDERR:\nboom\n\nExit code: 2"

    tr = FakeToolRegistry({"exec": exec_handler})
    execu = ScriptExecutor(tr)
    step = _step("script")
    result = await execu.execute(
        step,
        {"kind": "shell", "code": "false", "timeoutMs": 500},
        _ctx(),
    )
    assert result.status == "error"
    assert "script_nonzero_exit" in (result.error or "")


@pytest.mark.parametrize(
    "bad",
    [
        {"kind": "bogus", "code": "x", "timeoutMs": 500},
        {"kind": "shell", "code": "", "timeoutMs": 500},
        {"kind": "shell", "code": "ok", "timeoutMs": 50},
        {"kind": "shell", "code": "ok", "timeoutMs": 60_001},
        {"kind": "shell", "code": "ok", "timeoutMs": 500, "stdin": 123},
    ],
)
async def test_script_executor_validates_args(bad):
    tr = FakeToolRegistry({"exec": "Exit code: 0"})
    execu = ScriptExecutor(tr)
    result = await execu.execute(_step("script"), bad, _ctx())
    assert result.status == "error"
    assert (result.error or "").startswith("workflow.validation.")


def test_parse_exec_output_splits_stdout_stderr_exit():
    raw = "line1\nline2\n\nSTDERR:\nwarn\n\nExit code: 3"
    parsed = _parse_exec_output(raw)
    assert parsed["exit_code"] == 3
    assert parsed["stdout"] == "line1\nline2"
    assert parsed["stderr"] == "warn"


# ---------------------------------------------------------------------------
# LlmExecutor
# ---------------------------------------------------------------------------


async def test_llm_executor_text_mode_returns_content():
    provider = FakeProvider(FakeLLMResponse("hi there"))
    execu = LlmExecutor(llm_provider=provider)
    result = await execu.execute(
        _step("llm"),
        {"userPrompt": "ping", "maxTokens": 64},
        _ctx(),
    )
    assert result.status == "ok"
    assert result.output["content"] == "hi there"
    assert result.output["usage"]["promptTokens"] == 5


async def test_llm_executor_json_mode_parses():
    provider = FakeProvider(FakeLLMResponse('{"ok": true, "n": 2}'))
    execu = LlmExecutor(llm_provider=provider)
    result = await execu.execute(
        _step("llm"),
        {"userPrompt": "give me json", "responseFormat": "json"},
        _ctx(),
    )
    assert result.status == "ok"
    assert result.output["parsed"] == {"ok": True, "n": 2}


async def test_llm_executor_json_mode_errors_on_invalid():
    provider = FakeProvider(FakeLLMResponse("not-json"))
    execu = LlmExecutor(llm_provider=provider)
    result = await execu.execute(
        _step("llm"),
        {"userPrompt": "give me json", "responseFormat": "json"},
        _ctx(),
    )
    assert result.status == "error"
    assert "llm_parse" in (result.error or "")


async def test_llm_executor_requires_provider():
    execu = LlmExecutor(llm_provider=None)
    result = await execu.execute(
        _step("llm"),
        {"userPrompt": "hi"},
        _ctx(),
    )
    assert result.status == "error"
    assert "llm_config" in (result.error or "")


async def test_llm_executor_propagates_provider_error():
    provider = FakeProvider(
        FakeLLMResponse(None, finish_reason="error", error_type="rate_limit")
    )
    execu = LlmExecutor(llm_provider=provider)
    result = await execu.execute(
        _step("llm"),
        {"userPrompt": "hi"},
        _ctx(),
    )
    assert result.status == "error"
    assert "llm_failed" in (result.error or "")


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"userPrompt": ""},
        {"userPrompt": "ok", "temperature": 3.0},
        {"userPrompt": "ok", "maxTokens": 0},
        {"userPrompt": "ok", "responseFormat": "xml"},
    ],
)
async def test_llm_executor_validates_args(bad):
    provider = FakeProvider(FakeLLMResponse("x"))
    execu = LlmExecutor(llm_provider=provider)
    result = await execu.execute(_step("llm"), bad, _ctx())
    assert result.status == "error"
    assert (result.error or "").startswith("workflow.validation.")


# ---------------------------------------------------------------------------
# AgentExecutor
# ---------------------------------------------------------------------------


class FakeAgentSpec:
    def __init__(
        self,
        *,
        system_prompt: str = "you are a helper",
        input_schema: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> None:
        self.system_prompt = system_prompt
        self.input_schema = input_schema or {
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "required": ["q"],
        }
        self.output_schema = output_schema or {
            "type": "object",
            "properties": {"a": {"type": "string"}},
            "required": ["a"],
        }


class FakeAgentRegistry:
    def __init__(self, agents: dict[str, FakeAgentSpec]) -> None:
        self._agents = agents

    def get(self, name: str) -> FakeAgentSpec:
        if name not in self._agents:
            raise KeyError(name)
        return self._agents[name]


async def test_agent_executor_validates_args_against_input_schema():
    registry = FakeAgentRegistry({"helper": FakeAgentSpec()})
    provider = FakeProvider(FakeLLMResponse('{"a": "ok"}'))
    execu = AgentExecutor(agent_registry=registry, llm_provider=provider)
    result = await execu.execute(_step("agent", "helper"), {"nope": 1}, _ctx())
    assert result.status == "error"
    assert "agent_args" in (result.error or "")


async def test_agent_executor_validates_output_against_schema():
    registry = FakeAgentRegistry({"helper": FakeAgentSpec()})
    provider = FakeProvider(FakeLLMResponse('{"wrong": "shape"}'))
    execu = AgentExecutor(agent_registry=registry, llm_provider=provider)
    result = await execu.execute(
        _step("agent", "helper"), {"q": "hi"}, _ctx()
    )
    assert result.status == "error"
    assert "agent_output_schema" in (result.error or "")


async def test_agent_executor_unwraps_fenced_json_block():
    registry = FakeAgentRegistry({"helper": FakeAgentSpec()})
    provider = FakeProvider(FakeLLMResponse('```json\n{"a": "hi"}\n```'))
    execu = AgentExecutor(agent_registry=registry, llm_provider=provider)
    result = await execu.execute(
        _step("agent", "helper"), {"q": "hi"}, _ctx()
    )
    assert result.status == "ok"
    assert result.output == {"a": "hi"}


async def test_agent_executor_unknown_ref():
    registry = FakeAgentRegistry({})
    provider = FakeProvider(FakeLLMResponse('{"a": "hi"}'))
    execu = AgentExecutor(agent_registry=registry, llm_provider=provider)
    result = await execu.execute(
        _step("agent", "absent"), {"q": "hi"}, _ctx()
    )
    assert result.status == "error"
    assert "agent_not_found" in (result.error or "")


# ---------------------------------------------------------------------------
# build_default_executors
# ---------------------------------------------------------------------------


def test_build_default_executors_covers_every_kind():
    tr = FakeToolRegistry()
    table = build_default_executors(tool_registry=tr)
    assert set(table) == {"tool", "script", "agent", "llm"}
    assert isinstance(table["tool"], ToolExecutor)
    assert isinstance(table["script"], ScriptExecutor)
    assert isinstance(table["agent"], AgentExecutor)
    assert isinstance(table["llm"], LlmExecutor)

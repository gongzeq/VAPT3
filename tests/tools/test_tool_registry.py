from __future__ import annotations

from typing import Any

import pytest

from secbot.agent.tools.base import Tool
from secbot.agent.tools.registry import ToolRegistry
from secbot.agent.tools.skill import SkillTool, bind_skill_context
from secbot.agents.high_risk import HighRiskGate
from secbot.policy import PolicyContext, ScopeContract
from secbot.skills.metadata import SkillMetadata
from secbot.skills.types import SkillContext, SkillResult


class _FakeTool(Tool):
    def __init__(self, name: str):
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"{self._name} tool"

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> Any:
        return kwargs


def _tool_names(definitions: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for definition in definitions:
        fn = definition.get("function", {})
        names.append(fn.get("name", ""))
    return names


def test_get_definitions_orders_builtins_then_mcp_tools() -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool("mcp_git_status"))
    registry.register(_FakeTool("write_file"))
    registry.register(_FakeTool("mcp_fs_list"))
    registry.register(_FakeTool("read_file"))

    assert _tool_names(registry.get_definitions()) == [
        "read_file",
        "write_file",
        "mcp_fs_list",
        "mcp_git_status",
    ]


def test_prepare_call_read_file_rejects_non_object_params_with_actionable_hint() -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool("read_file"))

    tool, params, error = registry.prepare_call("read_file", ["foo.txt"])

    assert tool is None
    assert params == ["foo.txt"]
    assert error is not None
    assert "must be a JSON object" in error
    assert "Use named parameters" in error


def test_prepare_call_other_tools_keep_generic_object_validation() -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool("grep"))

    tool, params, error = registry.prepare_call("grep", ["TODO"])

    assert tool is not None
    assert params == ["TODO"]
    assert error == "Error: Invalid parameters for tool 'grep': parameters must be an object, got list"


def test_get_definitions_returns_cached_result() -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool("read_file"))
    first = registry.get_definitions()
    assert registry._cached_definitions is not None
    second = registry.get_definitions()
    assert first == second


def test_register_invalidates_cache() -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool("read_file"))
    first = registry.get_definitions()
    registry.register(_FakeTool("write_file"))
    second = registry.get_definitions()
    assert first is not second
    assert len(second) == 2


def test_unregister_invalidates_cache() -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool("read_file"))
    registry.register(_FakeTool("write_file"))
    first = registry.get_definitions()
    registry.unregister("write_file")
    second = registry.get_definitions()
    assert first is not second
    assert len(second) == 1


@pytest.mark.asyncio
async def test_execute_returns_structured_policy_denial_for_worker_blackboard() -> None:
    registry = ToolRegistry(
        policy_context=PolicyContext(caller_kind="worker", worker_id="worker-1")
    )
    registry.register(_FakeTool("blackboard_write"))

    result = await registry.execute(
        "blackboard_write",
        {"kind": "finding", "payload": {"title": "worker finding"}},
    )

    assert '"error": "policy_denied"' in result
    assert '"rule": "caller_kind"' in result


@pytest.mark.asyncio
async def test_execute_allows_unrestricted_tool_by_default() -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool("blackboard_write"))

    result = await registry.execute(
        "blackboard_write",
        {"kind": "finding", "payload": {"title": "pi finding"}},
    )

    assert result == {"kind": "finding", "payload": {"title": "pi finding"}}


@pytest.mark.asyncio
async def test_execute_policy_scope_deny_is_structured() -> None:
    registry = ToolRegistry(
        policy_context=PolicyContext(
            scope=ScopeContract(in_scope=("example.test",))
        )
    )
    registry.register(_FakeTool("create_agent"))

    result = await registry.execute(
        "create_agent",
        {"target": "evil.example.net"},
    )

    assert '"error": "policy_denied"' in result
    assert '"rule": "scope"' in result


@pytest.mark.asyncio
async def test_execute_worker_report_publish_denied() -> None:
    registry = ToolRegistry(
        policy_context=PolicyContext(caller_kind="worker", worker_id="worker-1")
    )
    registry.register(_FakeTool("report-html"))

    result = await registry.execute("report-html", {"scan_id": "scan-1"})

    assert '"error": "policy_denied"' in result
    assert '"rule": "caller_kind"' in result


@pytest.mark.asyncio
async def test_execute_ticks_budget_after_allowed_tool() -> None:
    class Budget:
        def __init__(self) -> None:
            self.calls: list[str | None] = []

        def status(self) -> str:
            return "HEALTHY"

        def on_tool_call(self, worker_id: str | None = None) -> None:
            self.calls.append(worker_id)

    budget = Budget()
    registry = ToolRegistry(
        policy_context=PolicyContext(
            caller_kind="worker",
            worker_id="worker-1",
            budget=budget,
        )
    )
    registry.register(_FakeTool("read_blackboard"))

    result = await registry.execute("read_blackboard", {})

    assert result == {}
    assert budget.calls == ["worker-1"]


@pytest.mark.asyncio
async def test_execute_write_blackboard_alias_routes_to_budget_allowlist() -> None:
    class Budget:
        def __init__(self) -> None:
            self.calls = 0

        def status(self) -> str:
            return "EXCEEDED"

        def on_tool_call(self, worker_id: str | None = None) -> None:
            del worker_id
            self.calls += 1

    budget = Budget()
    registry = ToolRegistry(policy_context=PolicyContext(budget=budget))
    registry.register(_FakeTool("write_blackboard"))

    result = await registry.execute("write_blackboard", {"kind": "summary"})

    assert result == {"kind": "summary"}
    assert budget.calls == 1


@pytest.mark.asyncio
async def test_execute_does_not_tick_budget_after_policy_denial() -> None:
    class Budget:
        def __init__(self) -> None:
            self.calls = 0

        def status(self) -> str:
            return "EXCEEDED"

        def on_tool_call(self, worker_id: str | None = None) -> None:
            del worker_id
            self.calls += 1

    budget = Budget()
    registry = ToolRegistry(policy_context=PolicyContext(budget=budget))
    registry.register(_FakeTool("create_agent"))

    result = await registry.execute("create_agent", {"target": "example.test"})

    assert "policy_denied" in result
    assert budget.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", ["list_dir", "glob", "grep"])
async def test_execute_filesystem_read_tools_route_through_workspace_policy(
    tmp_path,
    tool_name: str,
) -> None:
    registry = ToolRegistry(
        policy_context=PolicyContext(
            workspace=tmp_path,
            workspace_strict=True,
        )
    )
    registry.register(_FakeTool(tool_name))

    result = await registry.execute(tool_name, {"path": "../outside"})

    assert '"error": "policy_denied"' in result
    assert '"rule": "workspace"' in result


@pytest.mark.asyncio
async def test_execute_need_approval_calls_confirm_once(tmp_path) -> None:
    meta = SkillMetadata(
        name="danger-skill",
        display_name="Danger Skill",
        version="1.0.0",
        risk_level="critical",
        category="test",
        external_binary=None,
        network_egress="required",
        expected_runtime_sec=5,
        summary_size_hint="small",
        skill_dir=tmp_path,
    )
    calls: list[dict[str, Any]] = []

    async def _confirm(payload):
        calls.append(dict(payload))
        return True

    async def _run(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
        return SkillResult(summary={"ran": True, "scan_id": ctx.scan_id})

    gate = HighRiskGate()
    tool = SkillTool(
        meta=meta,
        input_schema={
            "type": "object",
            "properties": {"target": {"type": "string"}},
            "required": ["target"],
        },
        handler_run=_run,
        workspace=tmp_path,
        description="danger",
        high_risk_gate=gate,
    )
    registry = ToolRegistry(
        policy_context=PolicyContext(scan_id="scan-1", confirm=_confirm)
    )
    registry.register(tool)
    bind_skill_context(scan_id="scan-1", scan_dir=tmp_path, confirm=_confirm)

    result = await registry.execute("danger-skill", {"target": "example.test"})

    assert len(calls) == 1
    assert calls[0]["type"] == "high_risk_confirm"
    assert calls[0]["skill"] == "danger-skill"
    assert '"ran": true' in result
    assert [entry["action"] for entry in gate.audit.entries] == [
        "confirm_request",
        "confirm_approve",
    ]


@pytest.mark.asyncio
async def test_execute_need_approval_denial_audits(tmp_path) -> None:
    meta = SkillMetadata(
        name="danger-skill",
        display_name="Danger Skill",
        version="1.0.0",
        risk_level="critical",
        category="test",
        external_binary=None,
        network_egress="required",
        expected_runtime_sec=5,
        summary_size_hint="small",
        skill_dir=tmp_path,
    )

    async def _confirm(payload):
        assert payload["skill"] == "danger-skill"
        return False

    async def _run(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
        raise AssertionError("handler must not run when approval is denied")

    gate = HighRiskGate()
    tool = SkillTool(
        meta=meta,
        input_schema={
            "type": "object",
            "properties": {"target": {"type": "string"}},
            "required": ["target"],
        },
        handler_run=_run,
        workspace=tmp_path,
        description="danger",
        high_risk_gate=gate,
    )
    registry = ToolRegistry(
        policy_context=PolicyContext(scan_id="scan-1", confirm=_confirm)
    )
    registry.register(tool)

    result = await registry.execute("danger-skill", {"target": "example.test"})

    assert '"error": "user_denied"' in result
    assert [entry["action"] for entry in gate.audit.entries] == [
        "confirm_request",
        "confirm_deny",
    ]

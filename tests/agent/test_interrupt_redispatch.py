"""Tests for interrupt handling: subagent auto-redispatch, runner drain order,
and auto-continue context preservation (task 06-11-orchestrator)."""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from secbot.config.schema import AgentDefaults
from secbot.providers.base import LLMResponse, ToolCallRequest

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars


def _make_subagent_manager(tmp_path):
    from secbot.agent.subagent import SubagentManager
    from secbot.bus.queue import MessageBus

    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    return SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=MessageBus(),
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    )


def _status(task_id="sub-1"):
    from secbot.agent.subagent import SubagentStatus

    return SubagentStatus(
        task_id=task_id, label="label", task_description="do task",
        started_at=time.monotonic(),
    )


def _run_result(stop_reason, final_content="partial summary"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        final_content=final_content,
        error=None,
        tool_events=[],
    )


class TestSubagentNoAutoRetry:
    """After removing the auto-retry loop (v2), interrupted subagents must
    report incomplete to the orchestrator in a single runner.run() call.
    The orchestrator decides whether to re-dispatch."""

    @pytest.mark.asyncio
    async def test_interrupted_subagent_announces_incomplete_without_retry(self, tmp_path):
        mgr = _make_subagent_manager(tmp_path)
        mgr._announce_result = AsyncMock()
        mgr.runner.run = AsyncMock(
            return_value=_run_result("max_iterations", "got halfway through"),
        )

        status = _status()
        await mgr._run_subagent(
            "sub-1", "do task", "label",
            {"channel": "test", "chat_id": "c1"}, status,
        )

        # Exactly one runner.run call — no auto-retry.
        assert mgr.runner.run.await_count == 1
        assert status.retries == 0
        mgr._announce_result.assert_awaited_once()
        args = mgr._announce_result.await_args.args
        assert args[5] == "incomplete"
        assert "任务未完成" in args[3]
        assert "got halfway through" in args[3]

    @pytest.mark.asyncio
    async def test_context_exhausted_also_announces_incomplete(self, tmp_path):
        mgr = _make_subagent_manager(tmp_path)
        mgr._announce_result = AsyncMock()
        mgr.runner.run = AsyncMock(
            return_value=_run_result("context_exhausted", "context full"),
        )

        status = _status()
        await mgr._run_subagent(
            "sub-1", "do task", "label",
            {"channel": "test", "chat_id": "c1"}, status,
        )

        assert mgr.runner.run.await_count == 1
        mgr._announce_result.assert_awaited_once()
        args = mgr._announce_result.await_args.args
        assert args[5] == "incomplete"
        assert "上下文窗口已满" in args[3]

    @pytest.mark.asyncio
    async def test_completed_subagent_does_not_retry(self, tmp_path):
        mgr = _make_subagent_manager(tmp_path)
        mgr._announce_result = AsyncMock()
        mgr.runner.run = AsyncMock(return_value=_run_result("completed", "done"))

        status = _status()
        await mgr._run_subagent(
            "sub-1", "do task", "label",
            {"channel": "test", "chat_id": "c1"}, status,
        )

        assert mgr.runner.run.await_count == 1
        assert status.retries == 0
        assert mgr._announce_result.await_args.args[5] == "ok"


class TestRunnerDrainBeforeSummary:
    @pytest.mark.asyncio
    async def test_injections_drained_before_interrupt_summary(self):
        """A subagent result arriving at exhaustion must be appended to the
        conversation BEFORE the synthetic interrupt summary so the summary
        (and auto-continue) can see it."""
        from secbot.agent.runner import AgentRunner, AgentRunSpec

        provider = MagicMock()
        provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
            content="still working",
            tool_calls=[ToolCallRequest(id="call_1", name="list_dir", arguments={"path": "."})],
        ))
        tools = MagicMock()
        tools.get_definitions.return_value = []
        tools.execute = AsyncMock(return_value="tool result")

        drain_calls = {"n": 0}

        async def inject_cb(**kwargs):
            drain_calls["n"] += 1
            if drain_calls["n"] == 1:
                return []  # mid-loop drain: nothing pending yet
            if drain_calls["n"] == 2:
                return [{
                    "role": "user",
                    "content": "[Subagent 'scan' interrupted (task not completed — see summary below)]",
                    "injected_event": "subagent_result",
                    "subagent_task_id": "sub-9",
                }]
            return []

        runner = AgentRunner(provider)
        result = await runner.run(AgentRunSpec(
            initial_messages=[],
            tools=tools,
            model="test-model",
            max_iterations=1,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
            injection_callback=inject_cb,
        ))

        assert result.stop_reason == "max_iterations"
        assert result.had_injections is True
        injected_idx = next(
            i for i, m in enumerate(result.messages)
            if m.get("injected_event") == "subagent_result"
        )
        # The synthetic interrupt summary stays the final assistant message.
        assert result.messages[-1]["role"] == "assistant"
        assert result.messages[-1]["content"] == result.final_content
        assert injected_idx < len(result.messages) - 1


def _make_loop(tmp_path):
    from secbot.agent.loop import AgentLoop
    from secbot.bus.queue import MessageBus

    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    with patch("secbot.agent.loop.ContextBuilder"), \
         patch("secbot.agent.loop.SessionManager"), \
         patch("secbot.agent.loop.SubagentManager") as mock_sub_mgr:
        mock_sub_mgr.return_value.cancel_by_session = AsyncMock(return_value=0)
        loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path)
    return loop


def _announce(task_id, body="Result:\nscan failed midway"):
    return {
        "role": "user",
        "content": f"[Subagent 'scan' interrupted (task not completed — see summary below)]\n\nTask: scan host\n\n{body}",
        "injected_event": "subagent_result",
        "subagent_task_id": task_id,
    }


class TestAutoContinueSubagentContext:
    def test_unconsumed_results_block_extracts_and_dedupes(self, tmp_path):
        loop = _make_loop(tmp_path)
        messages = [
            {"role": "user", "content": "scan example.com"},
            {"role": "assistant", "content": "dispatching"},
            _announce("sub-1"),
            _announce("sub-1"),  # duplicate task_id — must be deduped
            _announce("sub-2", body="Result:\nport scan done"),
            {"role": "assistant", "content": "[interrupt summary]"},
        ]

        block = loop._build_unconsumed_results_block(messages)

        assert "中断前后到达的子代理结果" in block
        assert block.count("scan failed midway") == 1
        assert "port scan done" in block
        assert "重新派发" in block

    def test_unconsumed_results_block_empty_without_announces(self, tmp_path):
        loop = _make_loop(tmp_path)
        assert loop._build_unconsumed_results_block([]) == ""
        assert loop._build_unconsumed_results_block(
            [{"role": "user", "content": "hello"}]
        ) == ""

    @pytest.mark.asyncio
    async def test_auto_continue_prompt_includes_unconsumed_results(self, tmp_path):
        loop = _make_loop(tmp_path)
        loop.subagents.get_running_statuses_by_session.return_value = []

        captured_prompts: list[str] = []

        def fake_build_messages(*, current_message, **kwargs):
            captured_prompts.append(current_message)
            return [{"role": "user", "content": current_message}]

        loop.context.build_messages = MagicMock(side_effect=fake_build_messages)
        loop._run_agent_loop = AsyncMock(
            return_value=("continued and done", [], [], "completed", False),
        )

        prior = [
            {"role": "assistant", "content": "working"},
            _announce("sub-1"),
            {"role": "assistant", "content": "[interrupt summary]"},
        ]
        final_content, extra, stop_reason, _ = await loop._auto_continue(
            final_content="[interrupt summary]",
            stop_reason="max_iterations",
            session=MagicMock(),
            channel="test",
            chat_id="c1",
            message_id=None,
            metadata={},
            session_key="test:c1",
            pending_queue=None,
            prior_messages=prior,
        )

        assert stop_reason == "completed"
        assert final_content == "continued and done"
        assert len(captured_prompts) == 1
        prompt = captured_prompts[0]
        assert "会话中断续接" in prompt
        assert "中断前后到达的子代理结果" in prompt
        assert "scan failed midway" in prompt

# 智能体工具调用轮次上限与会话总结机制

## Goal

当主智能体或子智能体触达工具调用轮次上限（60次）或 `context_window_tokens` 耗尽时，触发结构化会话总结，明确任务未完成状态，并在主智能体场景下自动开启新会话续接任务。

## Requirements

### R1：轮次上限改为 60（全局统一）
- `schema.py` 中 `max_tool_iterations` 默认值从 200 改为 **60**
- 主智能体与子智能体共用同一上限

### R2：触发条件（双保险）
- **轮次耗尽**：`iteration >= max_iterations`
- **上下文耗尽**：`_snip_history` 后 token 估算仍超出 `context_window_tokens`（新增 stop_reason: `context_exhausted`）

### R3：混合摘要生成（方案 C）
- **优先**：触达上限后，追加一轮**无工具**的 LLM 调用，让模型归纳：
  - 已收集的信息
  - 已尝试的方法
  - 当前阻塞点（block）
  - 明确声明"任务未完成"
- **降级**：若 LLM 调用失败（context 已满/API 错误），fallback 到确定性格式化（基于 `tool_events` + `messages` 最后几轮）

### R4：子智能体中断上报
- `subagent.py` 中新增对 `stop_reason == "max_iterations"` / `"context_exhausted"` 的**显式处理分支**
- 以上述摘要作为结果，通过 `_announce_result` 上报父智能体，`status="incomplete"`（而非当前的 `"ok"`）
- 父智能体收到后可决定是否重新派发子智能体

### R5：主智能体自动续接新会话
- 主智能体触达上限后：
  1. 生成结构化摘要（R3）
  2. 以该摘要为初始上下文，**自动开启新会话**继续任务
  3. 新会话继承原 session 的 `session_key`，用户感知为"延续对话"
- 续接次数无上限（用户可通过 `/stop` 手动终止）

## Acceptance Criteria

- [ ] `max_tool_iterations` 默认值 = 60（schema.py）
- [ ] `runner.py` 中 `stop_reason` 新增 `"context_exhausted"` 值
- [ ] 摘要生成优先 LLM，LLM 失败时 fallback 到格式化（runner.py 新增 `_generate_interrupt_summary`）
- [ ] `subagent.py` 显式处理 `max_iterations` / `context_exhausted`，上报 `status="incomplete"`
- [ ] `loop.py` 中主智能体触达上限后自动续接新会话
- [ ] 现有测试不回归（`max_iterations` 测试用例中 `200` 需更新或参数化）

## Definition of Done

- 单元测试覆盖：摘要生成 LLM fallback 路径
- 单元测试覆盖：`stop_reason="context_exhausted"` 路径
- `secbot/agent/runner.py`、`loop.py`、`subagent.py` 修改完成
- 无 lint/typecheck 错误

## Technical Approach

### 核心数据流

```
runner.py::run()
  for iteration in range(max_iterations):
    ...
  else:  # max_iterations exhausted
    stop_reason = "max_iterations"
    summary = await _generate_interrupt_summary(spec, messages, tool_events)
    final_content = summary

  # context exhausted detected in _snip_history or pre-check:
  if token_estimate > context_window_tokens:
    stop_reason = "context_exhausted"
    summary = await _generate_interrupt_summary(spec, messages, tool_events)

subagent.py
  if result.stop_reason in ("max_iterations", "context_exhausted"):
    _announce_result(..., status="incomplete", result=summary)

loop.py
  if result.stop_reason in ("max_iterations", "context_exhausted"):
    # auto-continue: inject summary as new user message, reset iteration counter
    new_messages = [{"role": "user", "content": f"[会话中断续接]\n{summary}"}]
    await _run_agent_loop(new_messages, ...)
```

### `_generate_interrupt_summary` 设计

```python
async def _generate_interrupt_summary(
    spec: AgentRunSpec,
    messages: list[dict],
    tool_events: list[dict],
) -> str:
    """Hybrid: try LLM, fallback to deterministic format."""
    try:
        # Build a minimal prompt with last N messages + tool events
        context = _build_summary_context(messages, tool_events)
        resp = await provider.chat(
            messages=[{"role": "user", "content": SUMMARY_PROMPT + context}],
            tools=None,
            max_tokens=2048,
        )
        if resp.content:
            return resp.content
    except Exception:
        pass
    # Deterministic fallback
    return _format_deterministic_summary(tool_events, messages)
```

## Decision (ADR-lite)

- **摘要方式**：混合方案（LLM 优先 + 格式化降级），兼顾质量与可靠性
- **轮次上限**：全局 60，主子智能体统一，避免子智能体空转消耗 token
- **主智能体续接**：自动开新会话，保证长任务不丢失进度
- **子智能体不自动续接**：由父智能体决策是否重新派发，保持编排控制权

## Out of Scope

- 前端 UI 展示"会话已续接 N 次"状态（可在后续迭代加）
- 续接次数上限（当前依赖用户手动 `/stop`）
- context_window_tokens 耗尽的精确预检测（先实现基于 `_snip_history` 返回值的粗略检测）

## Technical Notes

### 关键文件
- `secbot/config/schema.py` L80: `max_tool_iterations: int = 200` → 改 60
- `secbot/agent/runner.py` L266-577: 主循环，需加 `context_exhausted` 检测 + `_generate_interrupt_summary`
- `secbot/agent/loop.py` L875-883: `stop_reason == "max_iterations"` 处理，需加续接逻辑
- `secbot/agent/subagent.py` L648-688: `stop_reason` 分支，需加 `"incomplete"` 分支
- `secbot/templates/agent/max_iterations_message.md`: 模板更新
- `secbot/agent/runner.py` `_snip_history` L1151-1205: 返回是否发生了截断

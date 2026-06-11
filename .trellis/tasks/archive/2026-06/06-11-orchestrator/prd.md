# 修复轮次耗尽后 Orchestrator 不重派子代理

## Goal

当工具调用轮次（max_iterations）耗尽导致任务中断时，未完成的子代理任务应被可靠地重新派发。目前两条链路都会导致不重派：① 子代理耗尽返回 incomplete 后 Orchestrator 只总结不重派；② Orchestrator 自身耗尽 auto-continue 续接后丢失子代理上下文。

## Requirements

1. **代码级自动重派（确定性兜底）**：子代理因 `max_iterations`/`context_exhausted` 中断时，SubagentManager 自动重派同一任务，携带中断摘要作为续接上下文；每个任务重试上限 2 次；重试期间不向 Orchestrator 发 incomplete announce（避免双重派发），重试成功发 ok、重试耗尽才发 incomplete。
2. **修复续接上下文丢失**：
   * `runner.py` max_iterations 分支：在生成中断摘要**之前** drain 注入消息，使摘要能反映已到达的子代理结果。
   * `_auto_continue` 续接 prompt 携带本轮已 drain 但未被处理的子代理结果（含 incomplete announce），而不仅是 running 列表。
   * `_build_subagent_context_block` 覆盖"已结束但 Orchestrator 尚未消费结果"的子代理。
3. 重派的子代理沿用原 agent spec、scan_id、session 绑定。

## Acceptance Criteria

* [x] 子代理轮次耗尽 → 自动重派（带中断摘要），最多 2 次；重试成功 announce ok，重试耗尽 announce incomplete
* [x] 重试期间无重复派发（LLM 路径与代码路径不冲突）
* [x] Orchestrator 轮次耗尽时，中断摘要生成前先 drain 注入消息
* [x] auto-continue 续接 prompt 包含 incomplete/未消费的子代理结果
* [x] 重派有上限，无死循环
* [x] 单元测试覆盖：runner drain 顺序、auto-continue 上下文块、自动重派 + 重试上限

## Definition of Done

* Tests added/updated（tests/agent/）
* Lint / typecheck / CI green
* ARCHITECTURE.md 中断/续接章节如有则同步更新

## Technical Approach

* `secbot/agent/subagent.py`：`_dispatch` 的 max_iterations/context_exhausted 分支改为：retry_count < 2 时把 interrupt_summary 拼入原 task 重新执行（复用同一 task_id 或派生 task_id，状态广播为 retrying）；耗尽后才走现有 incomplete announce。
* `secbot/agent/runner.py:613-629`：将 `_try_drain_injections` 提前到 `_generate_interrupt_summary` 之前。
* `secbot/agent/loop.py`：`_auto_continue` 收集上一轮 drained 的 subagent_result 注入消息并拼入续接 prompt；`_build_subagent_context_block` 扩展覆盖已结束未消费的任务。

## Decision (ADR-lite)

**Context**：重派目前纯靠 announce 模板提示 LLM，且 Orchestrator 耗尽续接时丢失子代理上下文，两条链路都会停滞。
**Decision**：上下文丢失修复 + 代码级自动重派（上限 2 次）两者结合。
**Consequences**：可靠性最高；改动面较大（subagent/runner/loop 三处）；需防 LLM 路径与代码路径双重派发——通过重试期间不发 incomplete announce 解决。

## Out of Scope

* 子代理 max_iterations 配额本身的调整
* Orchestrator `_MAX_CONTINUATIONS` 数值调整
* announce 模板措辞优化以外的 prompt 工程

## Technical Notes

* 相关文件：`secbot/agent/loop.py`（_auto_continue:587, _build_subagent_context_block:562, _MAX_CONTINUATIONS:560）、`secbot/agent/runner.py`（max_iterations 分支:613-629）、`secbot/agent/subagent.py`（_dispatch 中断分支:687-714, _announce_result:745）、`secbot/templates/agent/subagent_announce.md`
* 子代理 per-agent max_iterations 已由 9e4c5dbd7 修复，与本任务正交

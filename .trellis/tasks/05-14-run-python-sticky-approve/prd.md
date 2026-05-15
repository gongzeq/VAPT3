# run-python sticky approve per-session

> **依赖**：必须等 [`05-14-subagent-run-custom-python`](file:///Users/shan/Downloads/nanobot/.trellis/tasks/05-14-subagent-run-custom-python/prd.md) MVP 跑通且 PR2 合并后再启动。

## 现状评估（2026-05-14 更新）

在 MVP 实施过程中发现，[`HighRiskGate`](file:///Users/shan/Downloads/nanobot/secbot/agents/high_risk.py) 已经原生支持「**同一 gate 实例内的 sticky**」（见 `_approved_skills` + `guard` 的短路分支），场景覆盖：

- **父代理（AgentLoop）会话内**：单次 `scan` 生命周期内共用一个 gate 实例 → 父代理首次 approve 后，后续同名 critical skill 免审。✓
- **子代理（subagent）单 task 内**：单次 `_run_subagent` 生命周期共用一个 gate → 同一个 subagent 任务内多次 `run-python` 免审。✓

**本子任务仍然有价值的剩余边界**：

1. **跨 subagent 任务的 sticky**：父代理每次 spawn 子代理都会重新 `discover_skill_tools` 创建新 gate，因此「首次 approve」会在每个新 subagent 重复发生。
2. **跨 scan_id（新对话）的显式复用**：当前重启/新会话必然重置，本来就是 OK 行为；但若产品希望 session_key 粒度的持久化（例如同一 websocket 连接多次 scan 共享 sticky），需要外置缓存。
3. **可观测性标记**：tool_call 卡片目前不会显示「本次是 sticky 自动批准」；对审计是盲区。
4. **配置开关**：默认 sticky 生效没有 off 的办法，若某用户希望「每次都审批」（偏执模式）需要显式 opt-out。

建议启动前重新与 PM 对齐：上面哪些边界真的会阻塞业务？若都不迫切，本子任务可**降级为「可观测性 + opt-out 开关」两项小改动**，不做会话级状态机。

## Goal


为 `run-python` SkillTool（以及未来同等高风险 SkillTool）增加**会话级 sticky approve**：用户在同一会话内首次审批通过后，后续调用免审；新会话或 secbot 重启自动重置。

## Why（动机）

PoC 调试场景下，子代理常在一段对话内多次重写 / 迭代脚本——若每次都弹审批，会严重打断节奏。父任务 brainstorm 阶段（Q4）原本选定该方案，为避免 MVP 引入额外的状态机风险，先拆出独立交付。

## Requirements

1. 在 `SkillContext`（或 `bind_skill_context`）上挂一份会话级缓存：`_session_approvals: dict[(session_key, skill_name), bool]`。
2. `SkillTool.execute` 在调 `confirm` 回调前先查缓存；命中且为 True → 跳过 confirm，直接进 handler。
3. confirm 通过后写缓存；confirm 拒绝/超时不写缓存（拒绝是一次性的）。
4. 缓存生命周期 = 进程 / 显式注销（参考 SubagentManager 的 `_session_tasks` 注销路径）。新 `session_key` 自动绕开。
5. **可观测性**：sticky 命中时 tool_call 卡片显示 `auto-approved (sticky)` 标签，避免审计盲区。
6. **配置开关**：`ToolsConfig` 增加 `sticky_approve_per_session: bool`（默认 False，开启后才生效）；或者按 skill 粒度 opt-in（推荐后者）。

## Acceptance Criteria

- [ ] 同一 `session_key` 下首次 confirm=approve 后，后续 N 次 `run-python` 调用不再触发 confirm 回调
- [ ] 不同 `session_key`（new chat_id）首次仍触发 confirm
- [ ] secbot 进程重启后缓存清空
- [ ] confirm=deny 不写缓存（下次仍触发）
- [ ] 前端 tool_call 卡片在 sticky 命中时携带可见标记
- [ ] 已开关闭（默认 off）时行为完全等同当前 critical 流程，保证可回滚
- [ ] 单测：首次拒绝 / 首次同意后续免审 / 新 session_key 重审 / 进程级重置 / 开关关闭

## Out of Scope

- 跨进程持久化（不写盘 / DB）
- 超时自动失效（如 30 分钟未用即失效）——可作为后续增强
- 把 sticky approve 自动应用到所有 critical SKILL（默认 opt-in）

## Technical Notes

- 缓存键设计建议：`(session_key, skill_name, code_hash?)`——是否带 `code_hash` 决定「同会话不同代码是否需要重审」，倾向 **不带**（M2 PoC 调试场景下重写代码很常见，带 hash 等于没拆 PR2）。
- 注销时机：可挂到 `SubagentManager.cancel_by_session` 或新增 `SkillContext.clear_session(session_key)` 钩子。
- 与黑名单/限流协同：sticky 命中**不**绕过工作区/超时/输出截断等硬护栏，只跳过人工 confirm。

## Open Questions（待启动时再答）

- Q1: 配置粒度——全局开关 vs 每 SKILL opt-in？倾向后者（在 SKILL.md metadata 加 `sticky_approve: true`）。
- Q2: 是否带超时（例如 30min idle 失效）？
- Q3: 前端 sticky 标签视觉（badge/tooltip 选择）？

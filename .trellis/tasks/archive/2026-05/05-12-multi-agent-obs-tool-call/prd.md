# P0: 子 agent 工具调用结构化折叠卡 + 高危审批样式

## Goal

把当前文字型 `tool_hint` 升级为带 `tool_name / tool_args / status / duration_ms` 的结构化 `tool_call` agent_event，在前端 `MessageBubble.AgentEventCard` 渲染为可折叠卡片；顺手把 `request_approval` 卡的高危视觉对齐原型。**前端不展示工具原始输出（result），仅展示子 agent 的思考过程与调用元数据**。来源 [`webui/src/gap/assistant-multi-agent.md`](../../../webui/src/gap/assistant-multi-agent.md) Task 2（P0，约 1-2d）。

## What I already know

- 现状：`AgentLoop` 工具调用结果走 `_progress` → `tool_hint` 文本消息；前端 `TraceGroup` 把多条 `tool_hint` 折叠成 pre 行
- `broadcast_agent_event` 协议已支撑 6 类子事件，新增 `tool_call` 不需要新 frame
- `MessageBubble.AgentEventCard`（[`MessageBubble.tsx#L454-L577`](../../src/components/MessageBubble.tsx)）已 switch 6 种事件类型，新增分支即可
- `AskUserPrompt.tsx` 已支持 `variant="approval"`，但**无 `detail` 预格式化区、无 destructive 红色强调、无危险图标**
- 工具调用前后已经有 hook（`AgentHook.before_tool` / `after_tool`），可直接挂广播

## Decision Log

- **D1 tool_hint 兼容策略**：本期 `tool_call` event 与 `tool_hint` 文本**并存**广播，前端优先渲染 `tool_call`；`tool_hint` 留作回落，后续任务（非本期）才下线 tool_hint
- **D2 payload 字段范围**（brainstorm Q5）：**不流转工具原始输出**。payload 仅包含调用元数据 + args；`tool_args` 全量透出（一般 < 1KB），`result_snippet` / `result_full_url` **不存在**。用户看完整结果通过子 agent 后续的 `thought` / 总结文本渲染（本任务不涉及）。
- **D3 status 枚举 + critical 判定**（brainstorm Q6 + 补充）：`running | ok | error | critical`。
  - `critical` **基于 `SkillMetadata.is_critical()`**（即 SKILL.md 的 `risk_level: critical`）判定，不再维护独立硬编码集合；当前命中包含 `sqlmap-dump` 与 `hydra-bruteforce`，后续新 skill 只要在 SKILL.md 标 critical 自动生效
  - `critical` **不**与 `request_approval` 工具结果耦合；request_approval 被拒 / 超时 / 返错一律为 `error`，不混用 critical
  - critical skill 命中时 running / ok 均为 `status=critical`（前端持续红边框）；若用户拒绝导致 `SkillResult(summary={"user_denied": True})`，后端广播 `status=error`
- **D4 approval 卡 detail 区**：`AskUserPrompt` 的 `variant="approval"` 增加 `detail?: string` prop，渲染为 `<pre>`（保留命令换行 / 引号），不做 markdown 渲染避免误解析
- **D5 不重构 TraceGroup**：保留作为 `tool_hint` 回落渲染器；新的 `tool_call` 卡走独立组件 `ToolCallCard`
- **D6 广播范围**（brainstorm Q4）：**仅子 agent** 的工具调用广播 `tool_call`；orchestrator 的 4 工具（`delegate_task` / `read_blackboard` / `write_plan` / `request_approval`）继续走已有的 `orchestrator_plan` / `subagent_spawned` / `blackboard_entry` 专用 event，避免消息流出现双卡。
- **D7 critical 工具必须前端批准后执行**（brainstorm 补充）：复用已有 `HighRiskGate` + `ctx.confirm` 机制——`_SkillTool._run` 对 critical skill 自动走 `high_risk_gate.guard(...)`。**本任务不新增后端拦截逻辑**，仅需补齐前端批准回传通道。
- **D8 HighRiskGate ↔ 前端 approval 双向通道**（本任务新增范围）：现状 `ctx.confirm(payload)` 只会触发 `high_risk_confirm` 通知，前端 `NotificationPanel` 仅列表展示，**无法回传同意/拒绝 bool**→后端会 120s 超时（DEFAULT_CONFIRM_TIMEOUT_SEC）。本任务需打通：
  - 后端：WebUI Surface 实现 `ctx.confirm`，把 `high_risk_confirm` payload 作为 inline `ask_user` 消息（`variant="approval"`）广播到对应 chat；等待前端用户操作消息或应答→解除 `asyncio.Event` 阻塞
  - 前端：消息流遇到 `high_risk_confirm` 来源的 approval 卡时，动画 / 红边框 / 警告图标直接复用 F4 的样式；`detail` 区展示 `summary_for_user` + `args`。点击同意→ POST 同意回调；点击拒绝→ POST 拒绝；到期前端灰掉按钮显示“已超时”
  - NotificationPanel 仍正常接收 `high_risk_confirm` 通知（作为跨页面提醒），不改动

## Requirements

### 后端
- **B5** 在 [`secbot/agent/subagent.py`](../../../secbot/agent/subagent.py) 的 `before_tool` / `after_tool` 钩子里新增 `agent_event.type = "tool_call"` 广播（**仅子 agent，orchestrator 主 loop 不广播**）：
  - payload：`{ agent_name, tool_name, tool_args, status: "running"|"ok"|"error"|"critical", duration_ms?: int, tool_call_id: str }`
  - `before_tool` 推 `running`；`after_tool` 推 `ok` / `error`，由 `tool_call_id` 在前端配对
  - **status 判定源于 `SkillMetadata.is_critical()`**（即 `risk_level == "critical"`）；命中时 running / ok 覆写为 `critical`，不再硬编码白名单
  - **不**包含 `result_snippet` / 工具返回值任何字段
- **B6（新增）HighRiskGate → WebUI Surface 打通**：实现 `ctx.confirm(payload)` 的 WebUI 适配器（位置建议在 `secbot/channels/websocket.py` 或 `secbot/agent/runner.py` 对 `SkillContext.confirm` 的注入点）：
  - 收到 `high_risk_confirm` payload 时，转化为一条 inline 消息 `{type: "ask_user", variant: "approval", summary_for_user, args, tool_call_id, detail}` 推到对应 chat
  - 创建一个 `pending_confirm[confirm_id] = asyncio.Future()`，等待前端 POST `/api/chat/{chat_id}/approval/{confirm_id}` 或老的 ask_user 回复消息解除
  - 120s 超时直接 resolve False（HighRiskGate 已有内置 timeout 逃生路径）
- 单元测试覆盖：
  - 非危险工具成功路径（running→ok）
  - 失败路径（running→error）
  - 高危工具 + 用户同意路径（running→critical，ok）
  - 高危工具 + 用户拒绝路径（running→error，带 user_denied）
  - 高危工具 + 超时路径（running→error，带 confirm_timeout）
  - orchestrator loop 不广播 `tool_call`

### 前端
- **F1** [`types.ts`](../../src/lib/types.ts) `AgentEventType` 增加 `"tool_call"`，`AgentEventPayload` 加对应字段
- **F2** [`useNanobotStream.ts`](../../src/hooks/useNanobotStream.ts) switch 增加 `tool_call` case；按 `tool_call_id` 在消息流里**合并** running → ok / error（避免出现两张卡）
- **F3** `MessageBubble.tsx` 新增 `ToolCallCard` 组件（**无 result 区**）：
  - 头：`tool_name` 徽章 + `agent_name` + `status` chip + 时长
  - args：JSON 美化预格式化（默认折叠，> 1 行才出展开按钮）
  - `status=critical` 视觉表现：红色边框 + `AlertTriangle` 图标，独立于 approval 卡
  - 强化 `subagent_spawned` 渲染（箭头 + 目标 agent 色块），与 `ToolCallCard` 视觉一致
- **F4** [`AskUserPrompt.tsx`](../../src/components/thread/AskUserPrompt.tsx) `variant="approval"` 强化：
  - 容器 border / 头部背景使用 `--destructive` 系列
  - 头部加 `AlertTriangle` 图标
  - `detail?: string` prop → `<pre class="ap-detail">` 渲染
  - 按钮组保持 3 个（同意 / 调整 / 拒绝），拒绝按钮使用 destructive 主色
- **F5（新增）`high_risk_confirm` 端到端接收**：[`useNanobotStream.ts`](../../src/hooks/useNanobotStream.ts) 添加 `high_risk_confirm` (或 `ask_user` 带 source=high_risk) 分支，渲染为 inline `AskUserPrompt.variant="approval"`；同意 / 拒绝 POST 回后端解除 `ctx.confirm` 阻塞。与 F4 样式共用。NotificationPanel 逻辑不变（跨页面提醒）

## Acceptance Criteria

1. 后端：触发一次 nmap skill 调用，前端消息流收到 `tool_call` running 卡，after_tool 钩子触发后**同一张卡**变为 ok 状态（不出现两张；通过 `tool_call_id` 配对）
2. 后端：触发 `sqlmap-dump` 或 `hydra-bruteforce` skill 时 **先广播 `tool_call running status=critical`**，随即进入 `ctx.confirm` 阻塞等待；非高危工具直接 `running→ok/error`
3. 后端 + 前端（端到端）：触发 sqlmap-dump 后，前端 inline 出 `AskUserPrompt.variant="approval"` 批准卡（红边框 + warning + detail pre）；点“同意”后 skill 才执行并回 `ok`，点“拒绝”后 skill **不实际调用 sqlmap 二进制**（可通过 HighRiskGate audit log 的 `confirm_deny` 验证），tool_call 最终状态 `error`
4. 后端：orchestrator 主 loop 调用 4 工具均 **不** 产生 `tool_call` event（由新增单测验证）
5. 后端：用户 120s 内不响应批准卡，HighRiskGate 超时回 `user_denied`，前端批准卡灰掉显示“已超时”，tool_call 最终状态 `error`
6. 前端：`tool_args` 超过 1 行时显示展开按钮；`ToolCallCard` **不**包含工具结果文本 / 预览区
7. 前端：`request_approval` 卡与 `high_risk_confirm` 卡视觉共享一套 approval 样式；`NotificationPanel` 收到 `high_risk_confirm` 仍能列表展示（作跨页面提醒）
8. `tool_hint` 文本消息仍可正常渲染（兼容回落）；现有 `TraceGroup` 与 `HighRiskGate` 单元测试不挂

## Open Questions

- _(2026-05-11 brainstorm 已清空：Q5 明确前端不展示工具原始输出；Q6 明确 critical 按 SkillMetadata.is_critical() 判定；补充明确 critical skill 必须前端批准后执行，依靠现有 HighRiskGate + 新增前后端批准回传通道。交付期新增再补。)_

## Out of Scope

- 下线 `tool_hint`（后续任务再做）
- Right Rail Trace Tab 的 `tool_call` 时间线（移至 Task 3）

## Technical Notes

### 关键文件
- `secbot/agent/subagent.py` — 子 agent tool hook
- `secbot/agent/hook.py` — `AgentHook` 抽象
- `secbot/agents/high_risk.py` — `HighRiskGate.guard()` / `build_confirmation_payload()` / `HighRiskDenied` / `DEFAULT_CONFIRM_TIMEOUT_SEC`
- `secbot/agent/tools/skill.py` — `_SkillTool._run` 已有 `high_risk_gate.guard(...)` 挂载点；`SkillContext.confirm` 的注入在 line 74
- `secbot/skills/types.py#L68` — `SkillContext.confirm` 默认为 `_default_no_confirm`，WebUI Surface 需覆写
- `secbot/channels/websocket.py` — `broadcast_agent_event` 复用 + 新增 approval 回传路由候选位置
- `webui/src/lib/types.ts`
- `webui/src/hooks/useNanobotStream.ts`
- `webui/src/components/MessageBubble.tsx`（新增 `ToolCallCard`）
- `webui/src/components/thread/AskUserPrompt.tsx`
- `webui/src/components/NotificationPanel.tsx` — `high_risk_confirm` 通知分支（不改动）
- `UI/prototype-assistant-multi-agent.html` — 视觉基线（`.tool-call`, `.approval` 样式）

---

## Spec Alignment & Pre-Development Notes (2026-05-11)

> 来源：`/trellis-before-dev` skill 对 `backend/high-risk-confirmation.md`、`backend/skill-contract.md`、`backend/websocket-protocol.md`、`frontend/index.md`、`frontend/component-patterns.md` 的对齐检查。实现前必读。

### A. 实现时必守 spec 约束（不可偏离）

1. **confirmation payload 字段已定，不再重取**：`high-risk-confirmation.md §2.1` 的 payload 结构（`type, skill, display_name, risk_level, summary_for_user, args, estimated_duration_sec, destructive_action, scan_id`）已是合约，`secbot/agents/high_risk.py` 的 `build_confirmation_payload` 已产出，B6 WebUI Surface **直接透传**，不再重套字段。
2. **Deny 后注入合成 tool_result**：`component-patterns.md §3.2` 强制要求 deny 时后端向 LLM context 注入 `{ status: "user_denied", reason? }` 的合成 `tool_result`，防止 orchestrator 同轮重发同一 tool_call。PRD B5 的 `status=error` 需附带 `reason: "user_denied"` 字段一同广播。
3. **denied status 色系对齐**：`component-patterns.md §2` 规定 `denied → --sev-info`（灰蓝）。PRD F3 的 `status` 枚举在前端渲染时，若 `reason=="user_denied"` 则 badge 用 `--sev-info`，不要简单 fallback 到 `--sev-critical`。
4. **audit 动作枚举不再扩充**：`high-risk-confirmation.md §4` 固化了 `confirm_request / confirm_approve / confirm_deny / confirm_timeout` 四种。现有 `HighRiskGate` 完全匹配，**B6 不新增 audit 动作**。
5. **WS client→server 回传复用 `scan.user_reply`**（决策 Q2）：`websocket-protocol.md §4` 已定 `{ ask_id, decision: "approve"|"deny", reason? }`。B6 将 `confirm_id → ask_id`，不新增 REST 路由、不新增 WS type。
6. **不新增第 4 个 top-level chat 组件**：`component-patterns.md §1 §5` 约束 `MessageBubble` 只有 `ToolCallCard / ScanResultTable / PlanTimeline` 三件套。F3 新增的实际上是 `ToolCallCard` 自身的子 agent 变体，**必须复用**，不得新起 `SubagentToolCallCard` 名字。
7. **测试文件名锁定**：`high-risk-confirmation.md §6` 指定 `tests/agent/test_high_risk_gating.py` / `test_high_risk_deny.py` / `test_confirm_timeout.py`。PRD B5/B6 的 6 类单测尽量并入这三份文件；新增的 orchestrator-不-广播测试可放 `tests/agent/test_tool_call_event.py`。
8. **Subprocess 路径不改**：`tool-invocation-safety.md` 全部约束保留，本 PR 不改 sandbox / 白名单 / network policy。

### B. Spec 豁免（待提交 `/trellis-update-spec` 更新）

- **位置**：`.trellis/spec/frontend/component-patterns.md §3 Destructive Confirmation Dialog`
- **当前 spec**：破坏性确认 **必须** 走 shadcn `<AlertDialog destructive>` 全屏弹窗 + 1s hover anti-misclick
- **本任务偏离**：按 [`UI/prototype-assistant-multi-agent.html#L1080-L1107`](../../../UI/prototype-assistant-multi-agent.html) 的产品原型，approval 卡 **inline** 在 chat bubble 内（orchestrator 消息气泡里嵌 `.approval` 卡，红色渐变背景 + warning + Approve/Deny 按钮行），**不** 用 AlertDialog。
- **补偿防误点约束**：F4 必须保留以下安全特性之一，代替原 spec 的“1s hover”：
  - 选项 1：**Deny 按钮默认高亮**，Approve 需再次点击确认（二次 tap）
  - 选项 2：Approve 点击后加 300ms 延迟 + 轻量 inline confirm 文案
  - 决策：实现时选 “选项 2”（保持 prototype 视觉，仅改行为），写入新 spec
- **行动**：本 PR 合入后立即运行 `/trellis-update-spec` 为 `component-patterns.md §3` 增 `3.3 Inline Approval Variant`，并串改 `frontend/index.md` Hard Rule #4（从“必须 AlertDialog”改为“破坏性确认走 shadcn AlertDialog destructive 或 inline `.approval` variant，二者均应满足防误点约束”）

### C. 开编前必点的 Thinking Guide 检查项

- **code-reuse**：`ctx.confirm` 默认实现 `_default_no_confirm` 在 `secbot/skills/types.py#L68`；CLI Surface 已在 `secbot/cli/onboard.py` 提供 confirm helper。**B6 新增 WebUI Surface 适配器时**，实现前先 grep `ctx.confirm = ` / `register_confirm` / `confirm_handler`，避免重复实现。
- **cross-layer**：boundary 数据流基线：
  ```
  _SkillTool._run → HighRiskGate.guard → ctx.confirm(payload)
     → WebUI Surface adapter → broadcast_agent_event(type="high_risk_confirm")
     → useNanobotStream → MessageBubble inline .approval
     → user click → scan.user_reply{ask_id, decision}
     → Surface resolve pending_confirm[ask_id].set_result(decision=="approve")
     → HighRiskGate 继续（approve）或短路（deny）→ audit.emit
  ```
  **validation 发生位置**：payload 结构在 `build_confirmation_payload` 输出时锁定；`decision` 枚举在 WS 进入 `scan.user_reply` handler 时锁定（只接受 `approve` / `deny`，其他字符串直接 400）。

### D. 开编顺序建议

1. B5（子 agent tool_call 事件 + `SkillMetadata.is_critical()` 判定）→ 单测验证
2. B6（WebUI Surface `ctx.confirm` 适配器 + `pending_confirm` Future 池 + `scan.user_reply` handler）→ 集成测（mock sqlmap-dump）
3. F1 + F2 协议 / hook 层 → 直接跟 B5 对
4. F3 `ToolCallCard` 渲染 → storybook / 视觉纠错
5. F4 `AskUserPrompt variant="approval" detail` 强化 + 防误点行为
6. F5 `high_risk_confirm` 分支接入 → 端到端 E2E（sqlmap-dump approve / deny / timeout）

### E. 黑名单确认（实现时再 grep 验证）

- 当前 `is_critical()` 命中集：`sqlmap-dump` / `hydra-bruteforce` 已在 SKILL.md 标 `risk_level: critical`
- **开编前必做**：`grep -rn "risk_level: critical" secbot/skills/` 确认全集，避免遗漏新 critical skill
- 验证检查：`grep -rn "CRITICAL_TOOL_NAMES" secbot/` 应为空（D3 已弃硬编码，若发现遗留 需在本 PR 删除）

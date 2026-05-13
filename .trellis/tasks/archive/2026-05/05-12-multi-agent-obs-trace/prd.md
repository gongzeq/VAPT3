# P1: Right Rail Trace Tab 复用 ActivityEventStream

## Goal

把 Dashboard 已有的 [`ActivityEventStream`](../../src/components/ActivityEventStream.tsx) 复用到对话页 Right Rail 的 `Trace` Tab，按 `chat_id` 过滤显示当前对话的 thought / tool_call / tool_result 时间线。来源 [`webui/src/gap/assistant-multi-agent.md`](../../../webui/src/gap/assistant-multi-agent.md) Task 3（P1，约 1d）。

## What I already know

- `ActivityEventStream.tsx` 组件已存在且仅 Dashboard 使用，**未按 `chat_id` 过滤**
- `useActivityStream.ts` hook 监听全局 `activity_event` frame，无 chat_id 维度
- 现有 `/api/events` 路由返回全局活动事件，**无 `chat_id` / `category` query 过滤**
- Right Rail 的 Tabs 容器在 Task 1 已搭好（默认 Blackboard，第二个 Tab 是 PromptSuggestions 残留）

## Decision Log

- **D1 复用而非重写**：直接给 `ActivityEventStream` 加 `chatId?: string` prop，组件内部基于 hook 返回数据做客户端过滤；hook 本身不动（避免影响 Dashboard）
- **D2 历史回填**：挂载时调 `GET /api/events?chat_id=...&limit=100` 拉历史；之后订阅 `activity_event` 增量
- **D3 Tab 顺序**：`Blackboard | Trace | Suggestions`（Suggestions 是兜底，未来可下线）
- **D4 不下线 PromptSuggestions**：本期保留作为第三 Tab，避免破坏当前用户的 prompts 入口

## Requirements

### 后端
- **B7** 改造现有 `/api/events` 路由：
  - 新增 query `?chat_id=` —— 仅返回 `payload.chat_id == chat_id` 的事件
  - 新增 query `?category=tool_call,tool_result,thought` —— 多值过滤
  - 不带 query 时保持现状（Dashboard 兼容）
  - 返回结构不变：`{events: [...], total: int}`
- 单元测试覆盖：带 chat_id 过滤 / 多 category 过滤 / 不带 query 兼容三条路径

### 前端
- **F7（增量）** Right Rail Tabs 容器（Task 1 已搭）追加第二 Tab `Trace`
- **F9** [`ActivityEventStream.tsx`](../../src/components/ActivityEventStream.tsx)：
  - 增加 props `chatId?: string`、`categories?: string[]`
  - 挂载时按 props 调 `GET /api/events?chat_id=...&category=...`
  - hook 增量数据按 `chatId` 客户端过滤（避免改 hook）
  - 视觉对齐 [`UI/prototype-assistant-multi-agent.html`](../../../UI/prototype-assistant-multi-agent.html) 的 `.trace-list` 时间线（agent 色块 + category 徽章 + 时间戳）

## Acceptance Criteria

1. 后端：`GET /api/events?chat_id=xxx&category=tool_call,thought` 仅返回该 chat 的指定类型事件
2. 后端：`GET /api/events`（不带 query）行为与改造前一致
3. 前端：Right Rail Trace Tab 切换后立即显示历史时间线（< 200ms 渲染）
4. 前端：在该 chat 触发新 tool_call 后，Trace Tab 自动追加新行（无需手动刷新）
5. Dashboard `ActivityEventStream` 不传 `chatId` 时行为未变

## Open Questions

- _(交付时如有再补充)_

## Out of Scope

- `tool_call` event 本身（依赖 Task 2 已完成）
- 时间线高级过滤（agent 多选 / 时间范围）—— 后续迭代
- 把 Trace Tab 做成默认 Tab（保持 Blackboard 默认）

## Technical Notes

### 关键文件
- `secbot/api/events.py` — `/api/events` 路由 handler
- `webui/src/components/ActivityEventStream.tsx`
- `webui/src/hooks/useActivityStream.ts`
- `webui/src/components/PromptSuggestions.tsx`（容器内部需要新增 Trace Tab）
- `UI/prototype-assistant-multi-agent.html` — `.trace-list` 视觉基线

### 依赖
- 依赖 [`05-12-multi-agent-obs-blackboard`](../05-12-multi-agent-obs-blackboard/prd.md) 完成 Right Rail Tabs 容器
- 依赖 [`05-12-multi-agent-obs-tool-call`](../05-12-multi-agent-obs-tool-call/prd.md) 完成 `tool_call` event（否则 Trace 时间线缺工具调用条目）

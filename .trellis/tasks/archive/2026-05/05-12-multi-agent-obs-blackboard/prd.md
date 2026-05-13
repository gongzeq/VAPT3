# P0: Right Rail Blackboard 面板 + 智能体实时状态

## Goal

让"刷新页面后右侧 Blackboard 不丢条目"和"Sidebar 智能体状态 chip 实时跟随后端"两个体验闭环。来源于 [`webui/src/gap/assistant-multi-agent.md`](../../../webui/src/gap/assistant-multi-agent.md) 的 Task 1（P0，约 2d）。

## What I already know

- 黑板自由化改造已完成（前缀 `[milestone]/[blocker]/[finding]/[progress]`）；`BlackboardEntry.text` 是自由文本，前端约定按前缀分色
- `Blackboard` 是 per-`AgentLoop` 内存实例，**没有按 `chat_id` 持久化或查询能力**
- `BlackboardCard.tsx` 组件已存在但**未被任何页面引用**，且无 kind 分色
- 当前 Right Rail 固定渲染 `PromptSuggestions`（KPI + prompts + 静态 mock `AGENTS[]`）
- `/api/agents` ([`secbot/api/agents.py#L31-L50`](../../../secbot/api/agents.py)) 仅返回静态注册表，无 runtime 字段
- `SubagentStatus` 已在 [`secbot/agent/subagent.py`](../../../secbot/agent/subagent.py) 维护；orchestrator 主 loop 状态可走 `AgentLoop` 心跳
- `broadcast_agent_event` 协议已存在 ([`secbot/channels/websocket.py#L1676-L1701`](../../../secbot/channels/websocket.py))，新增子类型不需要新 frame
- `useNanobotStream.ts#L270-L308` 已有 `agent_event` switch，可扩 case

## Decision Log

- **D1 Blackboard chat_id 归属**：先按"一个 chat = 一块黑板"实现（与原型一致）。orchestrator 多次调用同一 chat 时**累积**，刷新或重连页面时通过 HTTP 全量回填。
- **D2 BlackboardEntry.kind 字段**：仅新增**可选** `kind: str | None`，由 `write()` 基于 text 首个 `[xxx]` **自动抽取**。LLM 不需要传，前端拿到 `kind` 直接用，拿不到回退到正则识别。
- **D3 Blackboard 实例注册表**：在 `secbot/agent/blackboard.py` 旁新增 `BlackboardRegistry`（按 chat_id 索引），`AgentLoop` 启动时注册、结束时**保留**实例供后续查询；不做磁盘持久化（重启丢失可接受）。
- **D4 agent_status 事件**：`agent_event.type = "agent_status"` 在每个生命周期钩子（spawn / running / done / error）广播一次；不做节流（频率本身低）。
- **D5 Sidebar 智能体分组**：从 `PromptSuggestions.AGENTS[]` 迁入 `Sidebar.tsx` 底部，**保留** `PromptSuggestions` 中其他内容（KPI/prompts），后续 Task 3 再做 Right Rail Tabs 重构。
- **D6 条目上限策略**（brainstorm Q2）：后端 `BlackboardRegistry` 不对条目数量做硬上限（单次扫描上限由业务自然收敛）；**前端 `BlackboardPanel` 默认仅渲染最近 100 条**，超出时头部提示 `显示最近 100 / 共 N 条`，暂不做“查看全部”弹窗（留作 P2 增强）。
- **D7 API 兼容**（brainstorm Q3）：`/api/agents` **不改默认响应**，仅在收到 `?include_status=true` 时拼接 `status / current_task_id / last_heartbeat_at` 三字段；老调用方零改动。

## Requirements

### 后端
- **B1** [`secbot/api/agents.py`](../../../secbot/api/agents.py) `handle_list_agents` 响应追加：
  - `status: "idle" | "running" | "queued" | "offline"`
  - `current_task_id: str | None`
  - `last_heartbeat_at: str | None`（ISO 时间）
  - 数据来源：`SubagentManager._task_statuses` + 主 loop 心跳快照
- **B2** 新增 `secbot/api/blackboard.py`：
  - `GET /api/blackboard?chat_id=...` → 返回 `{entries: BlackboardEntry[]}`
  - 通过新增的 `BlackboardRegistry` 按 chat_id 检索
  - 注册到 `secbot/api/server.py`
- **B3** [`secbot/agent/blackboard.py`](../../../secbot/agent/blackboard.py) + [`secbot/agent/tools/blackboard.py`](../../../secbot/agent/tools/blackboard.py)：
  - `BlackboardEntry` 追加 `kind: str | None` 字段
  - `write()` 基于 text 正则 `^\s*\[(milestone|blocker|finding|progress)\]` 自动抽取 kind
  - `to_dict()` 透出 kind
  - 现有 `agent_event.blackboard_entry` 推送同步带上 kind
- **B6（裁剪进本任务）** 在 `SubagentManager` + orchestrator 的生命周期钩子里广播 `agent_event.type = "agent_status"`（payload: `agent_name, status, current_task_id`）

### 前端
- **F6** [`Sidebar.tsx`](../../src/components/Sidebar.tsx) 底部新增"专家智能体"分组：
  - 初始拉 `GET /api/agents?include_status=true`
  - 订阅 `agent_event.agent_status` 增量更新
  - 状态 chip 配色：`st-run` / `st-wait` / `st-idle` / `st-off`
- **F7（最小版）** Right Rail 区域添加 Tabs，默认 `Blackboard`，第二个 Tab 仍是原 `PromptSuggestions` 内容（Trace Tab 留给 Task 3）
- **F8** 重写 [`BlackboardCard.tsx`](../../src/components/BlackboardCard.tsx) → `BlackboardPanel.tsx`：
  - 挂载时 `GET /api/blackboard?chat_id=...` 全量初始化
  - 订阅 `agent_event.blackboard_entry` 增量追加
  - 按 `entry.kind`（或 text 前缀回退）渲染 4 色：`milestone/blocker/finding/progress`
  - `blocker` 应用呼吸动画
  - 头部显示 `LIVE` 徽章 + `显示最近 100 / 共 N 条`（N ≤ 100 时仅显示总数）
  - 内部只保留 `entries.slice(-100)` 渲染，避免长会话 DOM 膨胀
- **F10（裁剪进本任务）** [`HomePage.tsx`](../../src/pages/HomePage.tsx) 把 `rightRail` 切到新的 Tabs 容器

## Acceptance Criteria

1. 后端：`GET /api/agents?include_status=true` 返回所有 agent + runtime 字段；`GET /api/blackboard?chat_id=<existing>` 返回该 chat 已有条目数组
2. 后端：单元测试覆盖 `BlackboardRegistry` 按 chat_id 隔离 + `BlackboardEntry.kind` 自动抽取（含无前缀/未知前缀回退为 None）
3. 前端：刷新页面后 Right Rail Blackboard Tab 立即显示历史条目（不依赖 WS）
4. 前端：在两个浏览器 tab 打开同一 chat，A 触发子 agent，B Sidebar 智能体 chip 在 1s 内变为对应状态
5. 前端：`blocker` 类条目肉眼可见红色 + 呼吸动画
6. 不破坏现有 `PromptSuggestions` 已有 KPI 与 prompts；`/api/agents` 老调用方（不带 query）响应体字节级一致
7. 长会话场景：后端返回 500 条时前端 DOM 仅渲染最近 100，头部正确显示 `显示最近 100 / 共 500 条`

## Open Questions

- _(2026-05-11 brainstorm 已清空，交付期新增再补)_

## Out of Scope

- ThreadHeader 顶栏改造、迭代/Token chip（gap 文档已明确不做）
- `tool_call` 结构化卡（移至 Task 2）
- Trace Tab 时间线（移至 Task 3）
- 自定义 prompt 输入框（移至 Task 4）

## Technical Notes

### 关键文件
- `secbot/api/agents.py` — `/api/agents` 路由 handler
- `secbot/api/server.py` — 路由注册中心
- `secbot/agent/blackboard.py` — 数据模型 + 新增 `BlackboardRegistry`
- `secbot/agent/tools/blackboard.py` — write/read tool
- `secbot/agent/subagent.py` — 生命周期钩子，新增 `agent_status` 广播
- `secbot/agent/loop.py` — orchestrator 主 loop 心跳源
- `secbot/channels/websocket.py` — `broadcast_agent_event` 复用
- `webui/src/components/Sidebar.tsx` — 智能体分组
- `webui/src/components/BlackboardCard.tsx` — 重写为 panel
- `webui/src/components/PromptSuggestions.tsx` — 旧右栏，迁出 AGENTS 后保留其余
- `webui/src/lib/types.ts` — `AgentEventType` 增加 `agent_status`
- `webui/src/hooks/useNanobotStream.ts` — `agent_event.agent_status` switch case

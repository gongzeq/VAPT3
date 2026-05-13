# Gap: 智能助手多智能体可观测原型

> 基线参考：[`UI/prototype-assistant-multi-agent.html`](../../../UI/prototype-assistant-multi-agent.html)（v2 原型，对齐 secbot 海蓝主题的 Shell / ThreadShell / Right Rail 视觉语言）。
> 目标：把原型里的"多智能体派发 + 思维链 + 工具调用 + 黑板 + 审批"全链路观测能力在现网 `webui/` + `secbot/` 上落地。

---

## 前端数据需求清单

按原型功能模块拆分，标识当前 `webui/` 的就绪度。

### ① Sidebar · 会话 + 智能体双分组

| 功能点 | 原型展示 | 当前实现 | 状态 |
|--------|----------|----------|------|
| 会话列表（搜索/归档/新建） | ✅ 顶部新建 + 最近对话 | [Sidebar.tsx](../../src/components/Sidebar.tsx) 已有搜索 + 归档按钮 | ✅ |
| "专家智能体" 分组（主 + 5 子） | ✅ 6 行 agent-row，头像 + 描述 + 状态 chip | 当前在右侧 `PromptSuggestions` 中，且是静态 mock（`AGENTS[]`） | 🔧 需迁移 + 实时 |
| agent 实时状态（running/wait/idle/off） | ✅ `st-run` / `st-wait` / `st-idle` / `st-off` | `/api/agents` 仅返回静态注册表；前端 `AGENTS[]` 写死 `"idle"/"running"/"queued"` | ❌ |

### ② ThreadShell · 顶栏（不做变更）

> 本次范围内**不对 [ThreadHeader.tsx](../../src/components/thread/ThreadHeader.tsx) 做任何改造**。原型里的「迭代 X/Y」「Token N」两个 chip 不落地；现有 `Streaming` chip + title + RightRail toggle 保持现状。

### ③ 消息流 · agent_event 渲染

| 事件 | 原型展示 | 当前 `MessageBubble.AgentEventCard` 渲染 | 状态 |
|------|----------|----------|------|
| `thought` 思维链折叠 | `<div class="think">…</div>` | [MessageBubble.tsx#L458-L500](../../src/components/MessageBubble.tsx) 已支持折叠展开 | ✅ |
| `orchestrator_plan` 阶段卡 | `write_plan` 徽章 + 5 步序号 + detail | 已支持（`ListChecks` + ol） | ✅ |
| `subagent_spawned` 派发卡 | **带箭头 + 目标 agent 色块** 的 delegate 视觉卡 | 当前仅显示 "已启动 + task_description" 文字行 | 🔧 视觉未对齐 |
| `subagent_status` 状态 | phase + iteration 计数 | 已支持（一行文字） | ✅ |
| `subagent_done` 完成/失败 | 绿/红色边框 + 结果摘要 | 已支持 | ✅ |
| `blackboard_entry` 黑板条目 | **消息流 inline + Right Rail 面板同步** | 消息流 inline 已支持；Right Rail 面板**不存在** | 🔧 只完成一半 |
| **`tool_call` 结构化折叠卡** | ✅ `tc-name` + `tc-args` JSON + `tc-status` + `tc-body` 键值对 | **缺失**：当前只有 `TraceGroup` 把 `tool_hint` 文本折叠成 pre 行 | ❌ |
| `request_approval` 高危审批卡 | ✅ 红色 `ap-head` + `ap-detail` 预格式化 + 3 个按钮 | [AskUserPrompt.tsx](../../src/components/thread/AskUserPrompt.tsx) 支持 variant="approval"，但无 `detail` 预格式化区、无危险色强调 | 🔧 样式未对齐 |

### ④ Right Rail · Blackboard / Trace 双 Tab

| 功能点 | 原型展示 | 当前实现 | 状态 |
|--------|----------|----------|------|
| Tabs 切换（Blackboard / Trace） | ✅ `.rail-tabs` | 当前 Right Rail 固定是 `PromptSuggestions`（KPI + prompts + agents mock） | ❌ |
| Blackboard 条目（按前缀分色） | ✅ `k-milestone / k-blocker / k-finding / k-progress`（blocker 呼吸红） | **前端无面板**；[BlackboardCard.tsx](../../src/components/BlackboardCard.tsx) 组件存在但**未被任何页面引用** | ❌ |
| Blackboard LIVE 徽章 + 条数 | ✅ | 缺 | ❌ |
| 黑板历史回填（刷新页面后） | — | WS 仅增量推；无 HTTP 拉取接口 → **刷新后黑板为空** | ❌ |
| Trace 时间线（thought/tool_call/tool_result 按 agent 分栏） | ✅ 9 条示例 | [ActivityEventStream.tsx](../../src/components/ActivityEventStream.tsx) 存在但**仅 Dashboard 使用**；未按 `chat_id` 过滤 | 🔧 未复用到对话侧 |
| PromptSuggestions 旧面板 | — | 需要作为"第三个 Tab"保留或移位 | 🔧 待重排 |

### ⑤ Composer · 4 工具白名单呼应

| 功能点 | 当前实现 | 状态 |
|--------|----------|------|
| Slash commands 下拉 | [ThreadComposer.tsx](../../src/components/thread/ThreadComposer.tsx) 已有 | ✅ |
| `可用工具：delegate_task / read_blackboard / write_plan / request_approval` 提示 | Composer 无这一 meta 文案 | 🟡 可选 |

---

## 后端缺口

### 缺失接口（4 个）

| 端点 | 方法 | 说明 | 优先级 |
|------|------|------|--------|
| `GET /api/agents?include_status=true` | GET | 扩展已有 `/api/agents`，追加 `status / current_task_id / last_heartbeat_at / iteration / max_iterations` | **P0** |
| `GET /api/blackboard?chat_id=...` | GET | 拉取某 chat 的黑板历史条目（用于刷新回填 + 初次挂载） | **P0** |
| `GET /api/events?chat_id=...&limit=100` | GET | 现有 `/api/events` 扩展 `chat_id` / `category` 过滤，供 Right Rail Trace 面板加载历史 | P1 |

参考 [`secbot/api/agents.py#L31-L50`](../../../secbot/api/agents.py) 现有实现 —— 只在 `handle_list_agents` 响应里追加运行时字段即可，不需要新增路由。

### 缺失 WebSocket 事件 / 字段（3 个）

| 事件 | 说明 | 使用场景 |
|------|------|----------|
| `agent_event.type = "tool_call"` | 统一承载子 agent 的工具调用（`tool_name`, `tool_args`, `status: running\|ok\|error\|critical`, `duration_ms`, `result_snippet`）—— 落在与 thought / plan 同一 frame，替代当前文字型 `tool_hint` | 消息流 tool-call 折叠卡 |
| `agent_event.type = "agent_status"` | 主/子 agent 全局状态机切换（`agent_name`, `status: idle\|running\|queued\|offline`, `current_task_id`）—— 用于 Sidebar 智能体分组的状态 chip | Sidebar 实时 chip |

> 以上两类都建议**复用现有 `broadcast_agent_event` 协议**（[`secbot/channels/websocket.py#L1676-L1701`](../../../secbot/channels/websocket.py)），只在前端 [`AgentEventType`](../../src/lib/types.ts) 枚举追加并在 [`useNanobotStream.ts#L270-L308`](../../src/hooks/useNanobotStream.ts) 的 switch 扩支路，避免引入新 frame 类型。

### 数据模型缺口

1. **`BlackboardEntry` 无 `chat_id` / `kind` 字段**
   - 现状：[`Blackboard`](../../../secbot/agent/blackboard.py) 是 **per-AgentLoop 内存实例**，没有按 `chat_id` 持久化或查询能力
   - 需求：`GET /api/blackboard?chat_id=...` 需要按 chat 检索 → 需要把 blackboard 挂到 `chat_id` 维度或注入 `chat_id` 到 entry
   - 建议：保持 `text: str` 自由文本的决策不变（见 memory `黑板通信规范：语义前缀自由文本+前端视觉分级`），仅新增**可选** `kind: Literal["milestone","blocker","finding","progress"] | None`（软约束，LLM 不填则前端按前缀正则识别回落）
   - 可选：`kind` 字段由后端在 `write()` 里基于 text 首个 `[xxx]` 前缀**自动抽取**（不强制 LLM 传），这样数据模型保持前向兼容

2. **Agent 无运行时状态表**
   - 与 [`home-assistant-data.md`](./home-assistant-data.md) 中 G1 相同 —— 需要在 [`SubagentManager`](../../../secbot/agent/subagent.py) 或心跳服务维护一份 `agent_name → SubagentStatus` 的快照，由 `/api/agents?include_status=true` 读取
   - 主 agent（orchestrator）的状态走 `AgentLoop` 心跳；子 agent 走 `SubagentManager._task_statuses`

---

## 已有但可直接复用的后端能力

| 能力 | 位置 | 用途 |
|------|------|------|
| `broadcast_agent_event` 统一协议 | [`secbot/channels/websocket.py#L1676-L1701`](../../../secbot/channels/websocket.py) | 承载新增 `tool_call` / `agent_status` / `turn_meta` 子类型，无需新 frame |
| `Blackboard.set_on_write` 回调 | [`secbot/agent/blackboard.py#L42-L44`](../../../secbot/agent/blackboard.py) | 当前已用于 WS 推送；新增 HTTP 拉取不影响该路径 |
| `SubagentStatus` 数据结构 | [`secbot/agent/subagent.py`](../../../secbot/agent/subagent.py) | 直接作为 `agent_status` event 的 payload 底座 |
| `broadcast_activity_event` 时间线协议 | [`secbot/channels/websocket.py`](../../../secbot/channels/websocket.py) | Trace Tab 可直接订阅，无需新增协议 |
| `AgentRegistry` | [`secbot/agents/registry.py`](../../../secbot/agents/registry.py) | `/api/agents` 静态部分 |
| `AskUserPrompt` 组件 | [`webui/src/components/thread/AskUserPrompt.tsx`](../../src/components/thread/AskUserPrompt.tsx) | 已区分 `variant="approval"`，只需强化样式不需重写 |
| `BlackboardCard` 组件 | [`webui/src/components/BlackboardCard.tsx`](../../src/components/BlackboardCard.tsx) | 存在但未引用；需要重写以支持 kind 分色 + 搬到 Right Rail |
| `ActivityEventStream` 组件 | [`webui/src/components/ActivityEventStream.tsx`](../../src/components/ActivityEventStream.tsx) | 直接搬到 Right Rail 的 Trace Tab，配合 `chat_id` 过滤 |

---

## 前端改造清单

| 编号 | 文件 / 组件 | 变更 | 依赖 |
|------|-------------|------|------|
| F1 | [`types.ts`](../../src/lib/types.ts) | `AgentEventType` 枚举增加 `"tool_call" \| "agent_status" \| "turn_meta"`；`AgentEventPayload` 追加对应字段 | 后端 B1-B3 |
| F2 | [`useNanobotStream.ts`](../../src/hooks/useNanobotStream.ts) | switch 新增 3 个 case → 产出 `UIMessage.kind="agent_event"` 或更新 Shell 级 store | F1 |
| F3 | `MessageBubble.AgentEventCard` | 新增 `tool_call` 渲染分支（头 / args / status chip / body 预格式化 + 折叠），强化 `subagent_spawned` 为派发卡（箭头 + 目标色块） | F1 |
| F4 | `AskUserPrompt.tsx` | `variant="approval"` 增加 `destructive` 色、危险图标、pre 预格式化详情 | — |
| F6 | `Sidebar.tsx` | 底部追加"专家智能体"分组（从 `PromptSuggestions.AGENTS[]` 迁入）+ 订阅 `agent_status` 实时 chip | B1 + F1 |
| F7 | 新建 `RightRail.tsx`（或重构 `PromptSuggestions.tsx`） | Tabs 切换：`Blackboard` / `Trace` / `Suggestions`，默认 Blackboard | F8/F9 |
| F8 | 重写 `BlackboardCard.tsx` → `BlackboardPanel.tsx` | 初始化 `GET /api/blackboard?chat_id=...` + 订阅 `agent_event.blackboard_entry` 增量 + 前缀自动分色（milestone/blocker/finding/progress，blocker 呼吸） | B2 |
| F9 | 在 Right Rail 复用 `ActivityEventStream.tsx` | 传入 `chat_id` 过滤；现有组件已支持 props 注入数据 | B3 |
| F10 | `HomePage.tsx` | 把 `rightRail={<PromptSuggestions>}` 换成 `rightRail={<RightRail>}` | F7 |

---

## 后端改造清单

| 编号 | 文件 | 变更 | 优先级 |
|------|------|------|--------|
| B1 | [`secbot/api/agents.py`](../../../secbot/api/agents.py) | `handle_list_agents` 响应追加 `status / current_task_id / last_heartbeat_at`；读取 `SubagentManager` + heartbeat 快照 | P0 |
| B2 | 新增 `secbot/api/blackboard.py` + 注册到 `server.py` | `GET /api/blackboard?chat_id=...` → 查询 per-chat 黑板快照；需要把 `Blackboard` 从 `AgentLoop` 内存挂到按 `chat_id` 索引的注册表 | P0 |
| B3 | [`secbot/agent/blackboard.py`](../../../secbot/agent/blackboard.py) + [`secbot/agent/tools/blackboard.py`](../../../secbot/agent/tools/blackboard.py) | `BlackboardEntry` 追加 `kind: str \| None`；`write()` 基于 text 首个 `[xxx]` 自动抽取 kind；to_dict 透出 | P0 |
| B5 | [`secbot/agent/loop.py`](../../../secbot/agent/loop.py) + [`secbot/agent/subagent.py`](../../../secbot/agent/subagent.py) | 工具调用 pre/post hook 广播 `agent_event.type = "tool_call"`（替换 / 增补现有 `tool_hint` 文本消息） | P0 |
| B6 | [`secbot/agent/subagent.py`](../../../secbot/agent/subagent.py) + orchestrator | 广播 `agent_event.type = "agent_status"`（running/idle/queued/offline），覆盖所有 agent 生命周期钩子 | P1 |
| B7 | 现有 `/api/events` 路由 | 追加 `?chat_id=` + `?category=` query 过滤 | P1 |

---

## 建议后续任务（分阶段）

### Task 1 · P0 对话观测完善（约 2d）
- B1（agent runtime status）+ F6（Sidebar 智能体分组，订阅 `agent_status`）
- B2 + B3（blackboard HTTP + kind 字段）+ F7/F8（Right Rail Blackboard 面板）
- **交付指标**：刷新页面后 Right Rail 黑板不丢失；Sidebar 智能体状态 chip 实时跟随后端变化。

### Task 2 · P0 工具调用结构化（约 1-2d）
- B5（`tool_call` agent_event 广播）+ F1/F2/F3（前端渲染）
- F4（approval 卡高危样式）
- **交付指标**：子 agent 的 nmap / sqlmap / hydra 等工具调用以结构化折叠卡展示，`request_approval` 视觉与原型对齐。

### Task 3 · P1 Trace 时间线复用到对话侧（约 1d）
- B7（`/api/events?chat_id=`）+ F7/F9（Right Rail Trace Tab 复用 `ActivityEventStream`）
- **交付指标**：右侧 Trace Tab 按 chat_id 实时显示 thought / tool_call / tool_result 时间线。

### Task 4 · P2 Composer 工具白名单提示（约 0.25d）
- F11（Composer 添加 `可用工具: delegate_task / read_blackboard / write_plan / request_approval` meta 行）
- **交付指标**：用户知道编排层只能用这 4 个工具，与主 agent 白名单策略（见 memory `05-12 orchestrator-tool-whitelist`）呼应。

---

## 待确认项

1. **黑板 `chat_id` 归属粒度**：原型假设"一个对话 = 一次编排任务 = 一块黑板"。需要确认实际场景下，一个 chat 内跨多次 orchestrator 调用时黑板是清零还是累积（B2 依赖此决策）。
2. **`tool_call` 与现有 `tool_hint` / `activity_event` 的关系**：建议 `tool_call` 作为结构化版本**替代** tool_hint 文本（前端 `TraceGroup` 可以兼容回落），`activity_event` 保留给 Dashboard 大屏；需要确认是否要完全下线 tool_hint。
3. **智能体"离线"定义**：是否依赖心跳超时（heartbeat ttl），以及 offline 态下是否允许 orchestrator 仍派发任务（delegate_task 应该挡回）。

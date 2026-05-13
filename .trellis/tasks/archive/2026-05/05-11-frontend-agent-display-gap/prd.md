# brainstorm: 前端思维链、子智能体、黑板展示缺口分析

## Goal

分析并定位当前系统中「前端思维链未显示」「子智能体调用未显示」「黑板模型未显示」的根因，明确所有缺口（gap）及其修复路径。

## What I already know

### 1. 思维链（Agent Thought Chain）
- 后端 `loop.py` `AgentHook.before_iteration` 中通过 `_on_progress` 发送 thought，但仅在 `not context.streamed_content` 时触发
- 后端 `broadcast_activity_event` 发送 `tool_call` / `tool_result`，**没有 `thought` category**
- 前端 `useNanobotStream.ts` **没有处理任何 thought / reasoning 相关事件**
- 前端 **不存在 `AgentThoughtChain` 组件**
- `secbot/agent/loop.py` 第131-135行：thought 通过 `_on_progress` 发送，但最终只渲染为普通 `tool_hint` 或 `progress` message

### 2. 子智能体（Subagent / Orchestrator）
- 后端 `SubagentManager.spawn()` 创建子智能体，仅通过 `message bus` 发布**最终结果**（`_announce_result`）
- 后端 **没有实时广播子智能体状态变化**（phase、iteration、tool_events 等）
- `broadcast_task_update` 存在于 `websocket.py`，但**没有任何调用方**
- 前端 `useNanobotStream.ts` **没有处理 `task_update` 事件**
- 前端 **不存在子智能体状态展示组件**
- `ThreadHeader.tsx` 中硬编码了 `"orchestrator · 4 个专家智能体在线"`，是静态文本

### 3. 黑板（Blackboard）
- 后端 `Blackboard` 类支持 `on_write` 回调，但**没有任何地方创建 Blackboard 时传入该回调**
- `broadcast_blackboard_update` 存在于 `websocket.py`，但**没有任何调用方**
- `broadcast_blackboard_update` 的 payload 是 `stats`（统计摘要），**不包含具体黑板条目**
- 前端 `useNanobotStream.ts` **没有处理 `blackboard_update` 事件**
- 前端 `BlackboardCard.tsx` 组件存在，但**没有任何地方引用/使用它**
- 前端 `types.ts` **没有定义 `BlackboardEntry` 类型**，但 `BlackboardCard.tsx` 引用了它（**存在编译错误**）
- 黑板工具 `BlackboardWriteTool` / `BlackboardReadTool` 已注册，但黑板实例生命周期管理不明

### 4. Activity Stream（活动流）
- 后端 `broadcast_activity_event` 被 `loop.py` 调用，发送 `tool_call` / `tool_result`
- 前端 `useActivityStream.ts` 处理 `activity_event`，但**仅用于 Dashboard / 侧边栏**，不注入聊天消息流

## Gap 清单

| # | 缺口 | 影响范围 | 严重度 |
|---|------|---------|--------|
| G1 | 后端未发送 `thought` 类型的 activity_event | 思维链无法展示 | P0 |
| G2 | 前端未处理 thought / reasoning WebSocket 事件 | 思维链无法展示 | P0 |
| G3 | 前端缺少 AgentThoughtChain 组件 | 思维链无法展示 | P0 |
| G4 | 后端 SubagentManager 未实时广播状态变化 | 子智能体进度不可见 | P0 |
| G5 | 后端未调用 `broadcast_task_update` | 子智能体任务状态不可见 | P0 |
| G6 | 前端未处理 `task_update` WebSocket 事件 | 子智能体任务状态不可见 | P0 |
| G7 | 前端缺少子智能体状态展示组件 | 子智能体调用不可见 | P0 |
| G8 | 后端 Blackboard 未设置 `on_write` 回调 | 黑板写入无前端通知 | P0 |
| G9 | 后端未调用 `broadcast_blackboard_update` | 黑板更新不可见 | P0 |
| G10 | `broadcast_blackboard_update` payload 为 stats 而非条目详情 | 黑板内容不可见 | P0 |
| G11 | 前端未处理 `blackboard_update` WebSocket 事件 | 黑板更新不可见 | P0 |
| G12 | 前端 `types.ts` 缺少 `BlackboardEntry` 类型定义 | 编译错误 + 黑板无法渲染 | P0 |
| G13 | 前端 `BlackboardCard.tsx` 未被引用 | 黑板组件无法使用 | P1 |

## 用户决策

- **方案选择**：3（先做后端数据流打通 — 统一设计 agent_event 广播协议）

## 统一协议设计方案

### 现状分析

当前后端有三套独立的广播方法：
- `broadcast_activity_event` — 仅发送 `tool_call` / `tool_result`，被 loop.py 调用
- `broadcast_blackboard_update` — **定义了但无人调用**，payload 为 `stats` 摘要
- `broadcast_task_update` — **定义了但无人调用**，payload 为任务元数据

前端有两套独立的事件消费路径：
- `InboundEvent` → `dispatch(chatId)` → `useNanobotStream`（聊天消息流）
- `ActivityEventFrame` → `dispatchActivity()` → `useActivityStream`（Dashboard 侧边栏）

**问题**：`activity_event` 走 global dispatch，不进入聊天消息流；`InboundEvent` 缺少 agent 相关事件类型。

### 推荐方案：新增 `agent_event` 统一事件

在 `InboundEvent` 联盟中新增 `agent_event` 变体，直接接入 per-chat dispatch，数据自然流入消息流。

**Wire 格式**：

```typescript
// 前端 types.ts 新增
export type AgentEventType =
  | "thought"           // 智能体思考过程
  | "subagent_spawned"  // 子智能体启动
  | "subagent_status"   // 子智能体状态更新
  | "subagent_done"     // 子智能体完成/失败
  | "blackboard_entry"; // 黑板新条目

export interface AgentEvent {
  event: "agent_event";
  chat_id: string;
  type: AgentEventType;
  payload: AgentEventPayload;
  timestamp: string;
}

export type AgentEventPayload =
  | { type: "thought"; agent: string; content: string }
  | { type: "subagent_spawned"; task_id: string; label: string; task_description: string }
  | { type: "subagent_status"; task_id: string; phase: string; iteration: number; tool_events?: any[] }
  | { type: "subagent_done"; task_id: string; label: string; status: "ok" | "error"; result?: string }
  | { type: "blackboard_entry"; id: string; agent_name: string; text: string; timestamp: number };
```

**后端广播方法**（替换现有的 `broadcast_blackboard_update` / `broadcast_task_update`）：

```python
async def broadcast_agent_event(
    self,
    *,
    chat_id: str,
    type: str,
    payload: dict[str, Any],
) -> bool:
    """Emit a unified ``agent_event`` frame scoped to ``chat_id``."""
    body = {
        "event": "agent_event",
        "chat_id": chat_id,
        "type": type,
        "payload": dict(payload),
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    return await self._broadcast_frame(body, chat_id=chat_id)
```

**调用点规划**：

| 事件类型 | 后端调用位置 | 触发条件 |
|----------|-------------|---------|
| `thought` | `loop.py` `before_iteration` | 每次迭代生成 thought 时 |
| `subagent_spawned` | `subagent.py` `spawn()` | 子智能体创建后立即发送 |
| `subagent_status` | `subagent.py` `_on_checkpoint` | phase/iteration 变化时 |
| `subagent_done` | `subagent.py` `_announce_result` | 子智能体完成/失败时 |
| `blackboard_entry` | `blackboard.py` `write()` | 通过 `on_write` 回调发送 |

**前端接入**：

1. `secbot-client.ts` `handleMessage` 识别 `agent_event` 并 `dispatch(chatId)`
2. `useNanobotStream.ts` 处理 `agent_event`，转换为 `UIMessage` 插入消息流
3. `MessageBubble` 根据 `message.kind` 渲染不同卡片（ThoughtCard / SubagentCard / BlackboardCard）

### 方案优劣

**Pros**：
- 单一事件类型，减少协议复杂度
- 直接接入聊天消息流，用户体验连贯（思维链/子智能体/黑板随对话滚动）
- 复用现有的 `_broadcast_frame` + `dispatch` 基础设施
- 前端只需扩展 `InboundEvent` 联盟 + 一个 hook 处理分支

**Cons**：
- Dashboard 的 activity stream 收不到这些事件（但现有 `activity_event` 已覆盖 tool_call/tool_result，可以并行保留）
- 消息流可能变得冗长（需要设计可折叠交互）

## Open Questions

1. 思维链展示是否需要在消息流中可折叠？（建议：默认可折叠，只显示首行）
2. `agent_event` 是否需要节流？当前 `activity_event` 有 1/s 节流，但 thought 和 blackboard 条目可能需要实时性
3. 黑板条目是随消息流滚动，还是在固定位置（如 ThreadHeader 下方）展示汇总面板？

## Technical Notes

### 相关文件
- `secbot/agent/loop.py` — thought 生成与 progress 推送
- `secbot/agent/subagent.py` — 子智能体生命周期管理
- `secbot/agent/blackboard.py` — 黑板数据模型
- `secbot/agent/tools/blackboard.py` — 黑板读写工具
- `secbot/channels/websocket.py` — WebSocket 广播方法
- `webui/src/hooks/useNanobotStream.ts` — 前端消息流处理
- `webui/src/components/BlackboardCard.tsx` — 黑板卡片组件（孤儿组件）
- `webui/src/lib/types.ts` — 前端类型定义
- `webui/src/components/MessageList.tsx` — 消息列表渲染
- `webui/src/components/thread/ThreadHeader.tsx` — 头部静态文本

## 实施状态

### 已完成

| 文件 | 修改内容 |
|------|---------|
| `secbot/channels/websocket.py` | 新增 `broadcast_agent_event()` 统一广播方法 |
| `secbot/agent/loop.py` | thought 生成时广播 `agent_event/thought`；创建 Blackboard 实例并注册工具；turn 级别绑定 `on_write` 回调 |
| `secbot/agent/subagent.py` | spawn / checkpoint / done 时广播子智能体生命周期事件 |
| `secbot/agent/blackboard.py` | 新增 `set_on_write()` 方法支持动态绑定/解绑回调 |
| `webui/src/lib/types.ts` | 扩展 `InboundEvent` + 新增 `AgentEvent` / `AgentEventPayload` / `BlackboardEntry` |
| `webui/src/lib/secbot-client.ts` | `handleMessage` 识别 `agent_event` 并 per-chat dispatch |
| `webui/src/hooks/useNanobotStream.ts` | `agent_event` 转为 `UIMessage(kind: "agent_event")` 插入消息流 |
| `webui/src/components/MessageBubble.tsx` | 新增 `AgentEventCard` 组件，按类型渲染 thought / subagent / blackboard 卡片 |
| `webui/src/components/BlackboardCard.tsx` | 修复 `timestamp` 可能为 undefined 的编译错误 |

### 测试结果
- Python: `103 passed`（websocket + loop + subagent 相关测试全部通过）
- TypeScript: 修改的文件无新增编译错误

### 遗留缺口
- ~~Blackboard 实例化点缺失~~ **已解决**：在 `AgentLoop.__init__` 中创建 `Blackboard` 实例，`_register_default_tools` 中注册 `BlackboardWriteTool` / `BlackboardReadTool`，`_run_agent_loop` 中绑定 `on_write` 回调（仅 websocket 渠道）并在 turn 结束时清理。

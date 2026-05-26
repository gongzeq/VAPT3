# Fix chat history display issues

## Goal

修复前端历史会话显示的三个问题：
1. 历史对话中显示的内容与实际对话不一致，日志信息泄漏到用户气泡中
2. 历史会话中智能体状态显示为"离线"，应该显示为"空闲"
3. 历史对话中黑板和资产面板为空，应该显示历史数据

## What I already know

### 前端架构
- **历史加载**: `useSessions.ts` 的 `useSessionHistory` hook 通过 `GET /api/sessions/{key}/messages` 加载历史
- **消息转换**: `buildHistoryMessages()` 函数将后端返回的 `RawHistoryMessage[]` 转换为 `UIMessage[]`
- **消息分类**: 通过 `role` 字段区分 user/assistant/tool，通过 `_kind` 字段区分 agent_event
- **实时流**: `useNanobotStream.ts` 处理 WebSocket 实时消息流
- **黑板/资产**: `BlackboardPanel.tsx` 和 `AssetsPanel.tsx` 通过 HTTP + WebSocket 加载数据

### 后端架构
- **会话存储**: `secbot/session/manager.py` 的 `Session` 类，消息存储在 JSONL 文件中
- **消息持久化**: `AgentLoop._save_turn()` 保存消息到 session
- **agent_event 持久化**: WebSocket channel 的 `broadcast_agent_event()` 将非临时事件持久化为 `role=assistant, _kind=agent_event`
- **Runtime context**: `ContextBuilder._RUNTIME_CONTEXT_TAG` 包裹的元数据块，在持久化时被 `_sanitize_persisted_blocks()` 过滤掉

### 问题根因分析

#### 问题1: 日志信息泄漏到用户气泡
**根因**: `buildHistoryMessages()` 在 `useSessions.ts:216-229` 处理 `role=user` 时，没有过滤掉非用户内容。后端可能将某些系统/日志消息错误地标记为 `role=user`，或者前端没有正确过滤 `_kind` 字段。

**证据**:
- `useSessions.ts:216`: `if (m.role === "user")` 直接接受所有 `role=user` 的消息
- 没有检查 `_kind` 或其他标记来排除系统消息
- 后端 `_save_turn()` 在 `loop.py:1764-1806` 保存消息时，只过滤了 `_kind=agent_event` (line 108)，但可能有其他类型的系统消息被错误标记

#### 问题2: 智能体状态显示"离线"
**根因**: `useAgents.ts` 通过 WebSocket 订阅 `agent_event.agent_status` 更新状态。历史会话没有活跃的 WebSocket 连接，因此智能体状态默认为初始的 HTTP 快照值（可能是 `offline`）。

**证据**:
- `useAgents.ts:68-88`: WebSocket 订阅只在 `chatId` 存在时激活
- 历史会话查看时，`chatId` 存在但没有活跃的 turn，WebSocket 不会推送 `agent_status` 更新
- 初始 HTTP 快照 (`fetchAgents`) 返回的 `status` 可能是 `offline`（当没有活跃任务时）

**正确行为**: 历史会话应该显示智能体为 `idle`（空闲），因为历史会话本身已经结束，智能体不是真正的"离线"。

#### 问题3: 黑板/资产面板为空
**根因**: `BlackboardPanel.tsx` 和 `AssetsPanel.tsx` 都依赖 `chatId` 来加载数据：
- HTTP 快照: `fetchBlackboard(token, chatId)` 和 `fetchAssetFeed(token, chatId)`
- WebSocket 订阅: `client.onChat(chatId, ...)` 监听实时更新

**问题**: 历史会话查看时，`chatId` 是有效的，但：
1. HTTP 端点可能没有返回历史数据（需要检查后端实现）
2. WebSocket 订阅对历史会话无效（没有新事件推送）

**证据**:
- `BlackboardPanel.tsx:82-103`: 通过 `fetchBlackboard(token, chatId)` 加载
- `AssetsPanel.tsx:115-137`: 通过 `fetchAssetFeed(token, chatId)` 加载
- 后端 `secbot/api/blackboard.py` 和 `secbot/api/asset_feed.py` 实现了 HTTP 端点
- 需要验证这些端点是否正确返回历史数据

## Requirements

### R1: 修复用户消息气泡中的日志泄漏
- 在 `buildHistoryMessages()` 中过滤掉非用户内容
- 检查后端是否错误地将系统消息标记为 `role=user`
- 确保只有真正的用户输入才渲染为用户气泡

### R2: 历史会话中智能体状态显示为"空闲"
- 检测当前是否在查看历史会话（非活跃 turn）
- 对于历史会话，将智能体状态覆盖为 `idle` 而不是 `offline`
- 不影响实时会话的状态显示

### R3: 历史会话中显示黑板和资产数据
- 验证后端 HTTP 端点是否返回历史数据
- 如果后端已支持，确保前端正确加载和显示
- 如果后端不支持，需要从消息流中重建黑板/资产快照

## Acceptance Criteria

- [ ] 历史会话中用户气泡只显示用户输入，不包含日志/系统信息
- [ ] 历史会话中智能体状态显示为"空闲"（空闲），不显示"离线"
- [ ] 历史会话中黑板面板显示该会话的历史黑板条目
- [ ] 历史会话中资产面板显示该会话的历史资产清单
- [ ] 实时会话的所有功能不受影响
- [ ] 在浏览器中测试：切换到历史会话，验证上述四点

## Definition of Done

- 代码修改完成并通过 lint/typecheck
- 在浏览器中手动测试历史会话和实时会话
- 确认所有 acceptance criteria 通过

## Out of Scope

- 重构消息持久化逻辑
- 修改后端 API 结构（除非必要）
- 优化黑板/资产面板性能

## Technical Approach

### 修复1: 用户消息过滤
**位置**: `webui/src/hooks/useSessions.ts:216-229`

**方案**: 在 `buildHistoryMessages()` 中，对 `role=user` 的消息增加额外检查：
- 排除 `_kind=agent_event` 或其他非用户标记
- 检查 `content` 是否以 `_RUNTIME_CONTEXT_TAG` 开头（虽然后端应该已过滤，但前端防御性检查）
- 可能需要检查后端日志，确认是否有错误的 `role=user` 标记

### 修复2: 智能体状态
**位置**: `webui/src/hooks/useAgents.ts` 或 `webui/src/components/Sidebar.tsx`

**方案A（推荐）**: 在 `useAgents` hook 中检测历史会话
- 添加参数 `isHistoricalSession: boolean`
- 当 `isHistoricalSession=true` 时，将所有 `status=offline` 的智能体覆盖为 `idle`

**方案B**: 在 `Sidebar` 或 `RightRail` 组件中，根据会话状态覆盖显示

### 修复3: 黑板/资产历史数据
**位置**: `webui/src/components/BlackboardPanel.tsx` 和 `AssetsPanel.tsx`

**步骤**:
1. 先验证后端 HTTP 端点是否返回数据（通过浏览器 DevTools Network 检查）
2. 如果后端已返回数据但前端未显示，检查前端解析逻辑
3. 如果后端未返回数据，有两个选项：
   - **选项A**: 修改后端 API 返回历史快照（需要修改 `secbot/api/blackboard.py` 和 `asset_feed.py`）
   - **选项B**: 前端从 `useSessionHistory` 返回的消息流中重建黑板/资产（扫描 `agent_event` 类型的消息）

**推荐**: 先检查后端，如果后端已支持则只需前端小改；如果后端不支持，优先选项B（前端重建），因为不需要修改后端 API。

## Technical Notes

### 文件清单
**前端**:
- `webui/src/hooks/useSessions.ts` - 历史消息加载和转换
- `webui/src/hooks/useAgents.ts` - 智能体状态管理
- `webui/src/components/BlackboardPanel.tsx` - 黑板面板
- `webui/src/components/AssetsPanel.tsx` - 资产面板
- `webui/src/components/Sidebar.tsx` - 可能需要传递历史会话标记

**后端**:
- `secbot/api/blackboard.py` - 黑板 HTTP 端点
- `secbot/api/asset_feed.py` - 资产 HTTP 端点
- `secbot/session/manager.py` - 会话读取逻辑
- `secbot/channels/websocket.py` - 会话消息端点

### 调试步骤
1. 启动 webui dev server: `cd webui && npm run dev`
2. 打开浏览器 DevTools
3. 切换到一个历史会话
4. 检查 Network 面板：
   - `GET /api/sessions/{key}/messages` 返回的消息结构
   - `GET /api/blackboard?chat_id=...` 是否返回数据
   - `GET /api/assets?chat_id=...` 是否返回数据
5. 检查 Console 面板是否有错误
6. 检查 React DevTools 中 `useSessionHistory` / `BlackboardPanel` / `AssetsPanel` 的 state

### 约束
- 不修改后端消息持久化逻辑（除非发现明确的 bug）
- 保持前端代码与现有架构一致
- 优先使用现有 API，避免新增端点

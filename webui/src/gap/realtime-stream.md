# Gap: Realtime Stream (SSE vs WebSocket)

## 后端现状

- **当前方案**：WebSocket 双向通道（`secbot/channels/websocket.py`），用于聊天消息 + session 管理。
- **模板假设**：SSE（Server-Sent Events）单向推送用于 TaskDetail 实时日志 + Finding 流。
- **差异**：模板中 `fetch + ReadableStream` 模式需要 HTTP POST 端点返回 SSE 流；当前 websockets 库仅支持 GET 且无 body。

## 临时方案

- TaskDetail 页面实时日志使用 **mock 轮询**（setInterval 模拟事件到达）。
- 聊天/会话核心保持 WebSocket 不变。
- Dashboard KPI 数据为静态 mock，不涉及实时推送。

## 后续迁移路径

1. **方案 A（推荐）**：在 aiohttp 子服务（端口 8766）上暴露 SSE 端点：
   - `GET /api/scans/{task_id}/events/stream` — 返回 `text/event-stream`
   - 前端用 `fetch` + `ReadableStream` 消费，支持带 Bearer token
   - 指数退避重连（1s → 30s max）

2. **方案 B**：复用现有 WebSocket 通道新增 event type：
   - 新增 `event:"task_log"` / `event:"finding_stream"` 消息类型
   - 优点：零新端口；缺点：单通道混合聊天+日志，断连影响全局

## 建议后续任务

1. 确定 SSE vs WS 扩展方案
2. 后端 SSE 端点实现（aiohttp StreamResponse）
3. 前端 `useTaskEvents` hook（替换 mock 轮询）
4. 断连重连 + connection badge 状态同步

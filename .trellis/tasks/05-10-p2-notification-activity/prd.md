# P2 · Notification Center + Activity Event Stream

> Parent: [05-10-backend-api-gap-fill](../05-10-backend-api-gap-fill/prd.md)
> Priority: P2 · Est: 2d · Depends on: P0（WS 事件基建）

## Goal

补齐通知中心（Navbar 铃铛）与大屏实时事件流（近 5 分钟活动），交付 WS `activity_event` 单事件推送。本期采用内存队列快速交付，不引入新表。

## Requirements

### HTTP 接口（3 个）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/notifications` | GET | 列表（`?unread=0\|1&limit=50&offset=0`），响应含 `unread_count` |
| `/api/notifications/{id}/read` | POST | 标记单条已读 |
| `/api/notifications/read-all` | POST | 全部已读 |
| `/api/events?since=&limit=50` | GET | 事件流（近 5 分钟默认，单次最多 50 条） |

### WebSocket 事件（1 个）

| 事件 | 说明 |
|------|------|
| `activity_event` | 单条智能体活动（thought / tool_call / tool_result），带 `category / agent / step / duration_ms / timestamp` |

### 通知源

通知由后端内部事件触发产生，典型来源：
- 高危漏洞新增（`severity=critical`）
- 扫描任务失败 / 完成
- 高危操作请求用户确认（对应 `high_risk_confirm`）

存储：`secbot/channels/websocket.py` 内维护环形缓冲（默认保留 500 条）。

## Contracts

### 1. `GET /api/notifications?unread=1&limit=50&offset=0`

```json
{
  "items": [
    {
      "id": "n-01JS...",
      "type": "critical_vuln|scan_failed|scan_completed|high_risk_confirm",
      "title": "高危漏洞新增 2 项",
      "body": "192.168.1.21 SSH 弱口令",
      "read": false,
      "created_at": "2026-05-10T12:38:00+08:00",
      "link": "/tasks/TASK-2026-0510-014"
    }
  ],
  "total": 23,
  "unread_count": 3
}
```

### 2. `POST /api/notifications/{id}/read` → `200 {"id":"n-01JS...","read":true}`

### 3. `POST /api/notifications/read-all` → `200 {"updated": 3}`

### 4. `GET /api/events?since=2026-05-10T12:33:00+08:00&limit=50`

```json
{
  "items": [
    {
      "id": "evt-...",
      "timestamp": "2026-05-10T12:38:04+08:00",
      "level": "critical|warning|info|ok",
      "source": "weak_password|port_scan|asset_discovery|report|orchestrator",
      "task_id": "TASK-2026-0510-014",
      "message": "10.0.4.21:22 命中弱口令字典 — root/admin123"
    }
  ]
}
```

### 5. WS `activity_event`

```json
{
  "event": "activity_event",
  "chat_id": "...",
  "category": "thought|tool_call|tool_result",
  "agent": "port_scan",
  "step": "→ 调用 tool: port_scan(target=\"192.168.1.0/24\")",
  "duration_ms": 1200,
  "timestamp": "..."
}
```

## Acceptance Criteria

- [ ] 通知中心内存队列容量可配（默认 500）；溢出时丢弃最旧。
- [ ] 高危漏洞新增时自动产生 `critical_vuln` 通知 —— 在 `secbot/cmdb/repo.py::insert_vulnerability` 返回前直接调用通知队列 `publish()`（**不**引入 observer/signal 抽象），函数签名保持不变。
- [ ] `GET /api/events` 支持 `since` 时间戳过滤；无参数时返回最近 5 分钟。
- [ ] WS `activity_event` 由 `secbot/agent/loop.py` 在工具调用前后广播，复用 P0 R2 已落地的 `broadcast_task_update` 节流模板（1s/event/scope），经 `WebSocketChannel` 注入下发。
- [ ] `activity_event` 的组装点复用 `build_tool_event_start_payload`（见 `secbot/agent/loop.py` L131 附近），不新增插桩点。
- [ ] 单元测试：
  - `tests/api/test_notifications.py` — 列表、已读、全读。
  - `tests/api/test_events.py` — since 过滤、空结果。
  - `tests/channels/test_ws_activity_event.py`。
- [ ] 前端：Navbar 新增铃铛下拉面板，订阅 `/api/notifications`；大屏底部事件流组件接入 `/api/events` + WS 合流。

## Out of Scope

- 通知持久化（重启丢失）；如需跨重启恢复再引表。
- 通知的用户级过滤（多租户场景，本期单用户）。
- 事件流的长期存储（本期仅近 5 分钟滚动窗口）。
- **前端 UI 组件交付**（Navbar 铃铛下拉面板、大屏底部事件流面板）—— 归 `webui` 侧后续任务承接，本任务仅产出后端接口 + WS 事件契约。PRD Requirements 第 103 行描述前端集成仅为验收参考路径，不计入本任务 DoD。

## Technical Notes

- Spec 复用：
  - 既有 `.trellis/spec/backend/websocket-protocol.md`（如需补事件条目，在实施期决定）
  - 既有 `.trellis/spec/backend/high-risk-confirmation.md`（触发 `high_risk_confirm` 通知源）
  - 既有 `.trellis/spec/backend/dashboard-aggregation.md` §R2 节流规范（`broadcast_task_update` / `broadcast_blackboard_update` 已定义 1s/event/scope 节流，本任务 `activity_event` 沿用）
- 既有切点（避免重复插桩）：
  - `secbot/agent/loop.py::build_tool_event_start_payload`（约 L131）已在工具调用起点组装 event payload —— 从此处 fork 出 `activity_event` 分支广播。
  - `secbot/channels/websocket.py::WebSocketChannel`（P0 R2 已注入 `subagent_manager` / `agent_registry`）：本任务追加 `notification_queue` 构造参数，保持与 P0 依赖注入风格一致。
- 主文件：
  - `secbot/channels/websocket.py` — 新 HTTP 端点 + 通知队列 + `activity_event` 广播
  - `secbot/agent/loop.py` — 工具调用前后发射 activity_event（复用 `build_tool_event_start_payload` 产物）
  - `secbot/cmdb/repo.py::insert_vulnerability` — 末尾对 `severity=critical` 直接 `notification_queue.publish()`，不新增 hook 层

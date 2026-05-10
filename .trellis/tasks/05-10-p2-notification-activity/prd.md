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
- [ ] 高危漏洞新增时自动产生 `critical_vuln` 通知（由 CMDB hook 或 Orchestrator 驱动）。
- [ ] `GET /api/events` 支持 `since` 时间戳过滤；无参数时返回最近 5 分钟。
- [ ] WS `activity_event` 由 `secbot/agent/loop.py` 在工具调用前后广播。
- [ ] 单元测试：
  - `tests/api/test_notifications.py` — 列表、已读、全读。
  - `tests/api/test_events.py` — since 过滤、空结果。
  - `tests/channels/test_ws_activity_event.py`。
- [ ] 前端：Navbar 新增铃铛下拉面板，订阅 `/api/notifications`；大屏底部事件流组件接入 `/api/events` + WS 合流。

## Out of Scope

- 通知持久化（重启丢失）；如需跨重启恢复再引表。
- 通知的用户级过滤（多租户场景，本期单用户）。
- 事件流的长期存储（本期仅近 5 分钟滚动窗口）。

## Technical Notes

- Spec 复用：
  - 既有 `.trellis/spec/backend/websocket-protocol.md`（如需补事件条目，在实施期决定）
  - 既有 `.trellis/spec/backend/high-risk-confirmation.md`（触发 `high_risk_confirm` 通知源）
- 主文件：
  - `secbot/channels/websocket.py` — 新 HTTP 端点 + 通知队列 + `activity_event` 广播
  - `secbot/agent/loop.py` — 工具调用前后发射 activity_event
  - `secbot/cmdb/repo.py::on_vulnerability_insert`（新 hook）— 高危漏洞触发通知

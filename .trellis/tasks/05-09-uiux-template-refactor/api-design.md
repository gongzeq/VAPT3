# 海盾智能体管控台 · 前端页面接口设计文档

> 文档版本：v1.0 · 2026-05-09
> 作用域：`.trellis/tasks/05-09-uiux-template-refactor/prototypes/` 下的 5 个 HTML 原型
> 依据：现有 secbot/nanobot 后端接口规范（见附录 A）
> 标记：`✅ 已存在` / `🛠️ 待开发` / `🔧 待扩展`（已有接口需新增字段）

---

## 0 · 全局规范

### 0.1 URL 前缀

- REST 业务接口：`/api/**`（复用现有）
- OpenAI 兼容接口：`/v1/**`（保留，供对话核心使用）
- WebSocket：`ws://{host}:{port}{path}?client_id=&token=`（默认 `ws://127.0.0.1:8765/`）
- 健康检查：`GET /health`

### 0.2 HTTP 方法约定

| 方法 | 用途 |
|------|------|
| `GET` | 查询、列表、详情、轻动作（复用现有 `GET /api/sessions/{key}/delete` 风格） |
| `POST` | 创建资源、执行命令（扫描、生成报告等） |
| `PUT` | 更新资源（整体替换或局部合并） |
| `DELETE` | 删除资源（正式删除动作，推荐方式） |

> 现有代码中 `/api/sessions/{key}/delete` 用 `GET`。新增接口一律使用 `DELETE` 语义更清晰的动词；如需保持兼容则附加 `GET` 别名。

### 0.3 响应包装

**裸对象（现有默认形态，本文档沿用）：**
```json
{ "field1": "...", "field2": [...] }
```

**错误响应（aiohttp 现有做法）：**
```json
{ "error": "human readable reason" }
```
HTTP 状态码承担错误类型语义（400/401/403/404/409/413/429/500/504）。

### 0.4 鉴权

- HTTP：`Authorization: Bearer <shared_secret>`
- 敏感值：走请求头 `X-Settings-Api-Key: <value>`，禁止放 URL
- WebSocket：`?token=<value>`（静态共享密钥 或 一次性签发 Token）

### 0.5 分页与排序

列表类接口统一支持：
```
?limit=50&offset=0
?sort=created_at&order=desc
?q=<keyword>           # 模糊搜索
?severity=critical,high  # 枚举筛选，逗号分隔
```
响应：
```json
{ "items": [...], "total": 128, "limit": 50, "offset": 0 }
```

### 0.6 时间戳

ISO 8601（带时区）：`2026-05-09T12:38:00+08:00`。前端统一用 Date 对象解析。

### 0.7 WebSocket 事件协议

**Server → Client 必含 `event` 字段：**
- `ready` / `attached` / `message` / `delta` / `stream_end` / `error`
- 新增扩展事件（本次重构需补）：`task_update` / `blackboard_update` / `log_append` / `high_risk_confirm` / `activity_event`

**Client → Server：**
- 纯文本或 `{"content":"..."}`
- `{"type":"new_chat|attach|message|stop", "chat_id":"...", ...}`

---

## 1 · 登录页 `01-login.html`

| # | 功能点 | 方法 | 路径 | 状态 |
|---|--------|------|------|------|
| 1.1 | 共享密钥登录 | `POST` | `/api/auth/login` | 🛠️ 待开发 非空都可以登录|
| 1.2 | 校验当前 Token | `GET`  | `/api/auth/whoami` | 不做，登录后都是admin权限 |
| 1.3 | 退出登录（清除服务端 session） | `POST` | `/api/auth/logout` | 🛠️ 待开发 |
| 1.4 | 签发短期 WebSocket Token | `GET`  | `/api/auth/ws-token` | 🔧 待扩展（现有 `tokenIssuePath` 可配但默认空） |

### 1.1 `POST /api/auth/login` — 🛠️ 待开发

**请求**
```json
{
  "shared_secret": "user-entered-secret",
  "remember_device": true
}
```

**响应 200**
```json
{
  "token": "nbwt_a1b2c3...",
  "expires_at": "2026-05-16T12:38:00+08:00",
  "user": {
    "uid": "UID-1024",
    "display_name": "shan",
    "role": "admin"
  }
}
```

**响应 401**
```json
{ "error": "Invalid shared secret" }
```

**说明**：现有后端通过 `channels.websocket.token` 或 bearer 方式做鉴权，但**没有登录页端点**。需新增一个把 `shared_secret` 换成会话 Token 的端点，并写入 httpOnly Cookie 或返回给前端 localStorage 持有。

### 1.2 `GET /api/auth/whoami` — 不做

**请求**：仅需 `Authorization: Bearer ...`

**响应 200**
```json
{ "uid": "UID-1024", "display_name": "shan", "role": "admin", "authenticated": true }
```

**响应 401**：用于前端判断是否跳登录页。

### 1.3 `POST /api/auth/logout` — 🛠️ 待开发

**响应 204**：无 Body。撤销服务端 Token 记录。

### 1.4 `GET /api/auth/ws-token` — 🔧 待扩展

现有配置 `channels.websocket.tokenIssuePath` 已定义路径但需映射到 `/api/auth/ws-token` 以便前端统一管理。返回一次性 Token 供 WS 握手使用。

**响应 200**
```json
{ "token": "nbwt_xxxx", "expires_in": 300 }
```

---

## 2 · 首页（智能助手） `02-home.html`

| # | 功能点 | 方法 | 路径 | 状态 |
|---|--------|------|------|------|
| 2.1 | 新建会话 | `POST` | `/api/sessions` | 🛠️ 待开发（现有只能通过 WS `type:"new_chat"` 隐式创建） |
| 2.2 | 列出会话 | `GET` | `/api/sessions` | ✅ 已存在 |
| 2.3 | 搜索会话（按关键词） | `GET` | `/api/sessions?q=...` | 🔧 待扩展（现有接口无 `q` 参数） |
| 2.4 | 获取会话消息 | `GET` | `/api/sessions/{key}/messages` | ✅ 已存在 |
| 2.5 | 删除会话 | `DELETE` | `/api/sessions/{key}` | 🔧 待扩展（现用 `GET /delete`，建议加 DELETE 别名） |
| 2.6 | 归档会话 | `POST` | `/api/sessions/{key}/archive` | 🛠️ 待开发 |
| 2.7 | 发送消息（流式） | WS | `{"type":"message","chat_id":"...","content":"..."}` | ✅ 已存在 |
| 2.8 | 停止当前回复 | WS | `{"type":"stop","chat_id":"..."}` | ✅ 已存在 |
| 2.9 | 上传附件（图片/文档） | `POST` | `/v1/chat/completions` (multipart) | ✅ 已存在 |
| 2.10 | 列出快捷指令 | `GET` | `/api/commands` | ✅ 已存在 |
| 2.11 | 实时今日态势 KPI | `GET` | `/api/dashboard/summary` | 🛠️ 待开发 |
| 2.12 | 在线专家智能体列表 | `GET` | `/api/agents?include_status=true` | 🔧 待扩展（现有 `/api/agents` 不含实时 status） |
| 2.13 | WebSocket 连接状态与延迟 | WS | `ready` + `ping/pong` | ✅ 已存在 |
| 2.14 | 实时共享黑板数据推送 | WS | `event:"blackboard_update"` | 🛠️ 待开发 |
| 2.15 | 智能体思维链推送 | WS | `event:"activity_event"` (category=thought) | 🛠️ 待开发 |
| 2.16 | 通知中心（铃铛） | `GET` | `/api/notifications?unread=1` | 🛠️ 待开发 |
| 2.17 | 切换语言 | `GET` | `/api/settings/update?language=zh-CN` | 🔧 待扩展（现有 settings 未含 language） |

### 2.1 `POST /api/sessions` — 🛠️ 待开发

**请求**
```json
{ "title": "扫描 192.168.1.0/24 全段", "channel": "webui" }
```

**响应 201**
```json
{
  "key": "webui:0e1b...c8",
  "channel": "webui",
  "chat_id": "0e1b...c8",
  "created_at": "2026-05-09T12:38:00+08:00",
  "title": "扫描 192.168.1.0/24 全段"
}
```

### 2.3 `GET /api/sessions?q=...` — 🔧 待扩展

新增查询参数：`q`（标题/预览模糊匹配）、`limit`、`offset`、`archived=0|1`。

**响应 200**（扩展字段：`archived`）
```json
{
  "sessions": [
    {
      "key": "webui:xxx",
      "created_at": "...",
      "updated_at": "...",
      "title": "扫描 192.168.1.0/24 全段",
      "preview": "已发现 47 个资产，3 个高危…",
      "archived": false,
      "message_count": 12
    }
  ],
  "total": 23
}
```

### 2.11 `GET /api/dashboard/summary` — 🛠️ 待开发

**响应 200**
```json
{
  "asset_total": 2847,
  "asset_delta_24h": 128,
  "running_tasks": 7,
  "running_count": 3,
  "queued_count": 4,
  "critical_vuln_total": 14,
  "critical_vuln_delta_24h": 2,
  "today_reports": 9,
  "pending_review": 3,
  "generated_at": "2026-05-09T12:38:00+08:00"
}
```

### 2.12 `GET /api/agents?include_status=true` — 🔧 待扩展

响应在现有字段基础上追加：
```json
{
  "agents": [
    {
      "name": "asset_discovery",
      "display_name": "资产发现智能体",
      "status": "idle|running|queued|offline",
      "current_task_id": "TASK-2026-0509-014",
      "progress": 0.68,
      "last_heartbeat_at": "2026-05-09T12:38:00+08:00"
    }
  ]
}
```

### 2.14 WebSocket `blackboard_update` — 🛠️ 待开发

服务器推送帧：
```json
{
  "event": "blackboard_update",
  "chat_id": "0e1b...c8",
  "timestamp": "2026-05-09T12:38:15+08:00",
  "stats": { "discovered_assets": 47, "open_ports": 183, "critical_findings": 3 }
}
```

### 2.15 WebSocket `activity_event` — 🛠️ 待开发

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

### 2.16 `GET /api/notifications` — 🛠️ 待开发

**响应 200**
```json
{
  "items": [
    { "id": "n-1", "type": "critical_vuln", "title": "高危漏洞新增 2 项",
      "body": "192.168.1.21 SSH 弱口令", "read": false, "created_at": "..." }
  ],
  "unread_count": 3
}
```

配套：`POST /api/notifications/{id}/read`、`POST /api/notifications/read-all`。


---

## 3 · 大屏分析 `03-dashboard.html`

| # | 功能点 | 方法 | 路径 | 状态 |
|---|--------|------|------|------|
| 3.1 | 立即扫描（从 Dashboard 触发） | `POST` | `/api/scans` | 🛠️ 待开发 |
| 3.2 | 导出当前快照 | `POST` | `/api/dashboard/snapshot` | 🛠️ 待开发 |
| 3.3 | 顶部实时徽章（last sync） | `GET` | `/api/dashboard/summary` | 🛠️ 待开发（同 2.11） |
| 3.4 | KPI 6 列 | `GET` | `/api/dashboard/summary` | 🛠️ 待开发（同 2.11，字段扩展） |
| 3.5 | 风险趋势图（7/30/90 天） | `GET` | `/api/dashboard/vuln-trend?range=30d` | 🛠️ 待开发 |
| 3.6 | 漏洞类型分布（饼图） | `GET` | `/api/dashboard/vuln-distribution` | 🛠️ 待开发 |
| 3.7 | 资产聚类柱图（按业务系统） | `GET` | `/api/dashboard/asset-cluster` | 🛠️ 待开发 |
| 3.8 | 最近报告列表（近 7 天） | `GET` | `/api/reports?range=7d&limit=5` | 🛠️ 待开发 |
| 3.9 | 实时事件流（近 5 分钟） | `GET` + WS | `/api/events?since=...` + `event:"activity_event"` | 🛠️ 待开发 |
| 3.10 | 暂停/恢复事件流（前端本地） | — | — | N/A（仅前端状态） |

### 3.1 `POST /api/scans` — 🛠️ 待开发

**请求**
```json
{
  "target": "192.168.1.0/24",
  "scope": { "ports": "22,3389,445,3306", "agents": ["asset_discovery","port_scan","weak_password","vuln_scan"] },
  "priority": "normal",
  "description": "Dashboard 一键触发"
}
```

**响应 201**
```json
{
  "task_id": "TASK-2026-0509-014",
  "scan_id": "01JS0...ULID",
  "status": "queued",
  "created_at": "2026-05-09T12:38:00+08:00"
}
```

数据模型基于 `secbot/cmdb/models.py::Scan`（字段 `id/target/status/scope_json/actor_id`）。

### 3.2 `POST /api/dashboard/snapshot` — 🛠️ 待开发

**请求**
```json
{ "format": "png|pdf", "include_charts": ["trend","distribution","cluster","reports","events"] }
```

**响应 200**（直接返回二进制 `Content-Type: application/pdf`）或
```json
{ "download_url": "/api/media/xxx/snapshot.pdf", "expires_at": "..." }
```

### 3.4 `GET /api/dashboard/summary`（KPI 全量字段）

扩展自 2.11：
```json
{
  "asset_total": 2847,
  "asset_delta_24h": 128,
  "asset_delta_pct": 4.7,
  "critical_vuln_total": 14,
  "critical_vuln_delta_24h": 2,
  "medium_vuln_total": 87,
  "medium_vuln_delta_24h": -5,
  "running_tasks": 7,
  "running_count": 3,
  "queued_count": 4,
  "compliance_grade": "A-",
  "compliance_score": 94.2,
  "today_reports": 9,
  "pending_review": 3,
  "generated_at": "..."
}
```

### 3.5 `GET /api/dashboard/vuln-trend?range=7d|30d|90d` — 🛠️ 待开发

**响应 200**
```json
{
  "range": "30d",
  "series": [
    { "name": "critical", "data": [ { "date": "2026-04-10", "count": 2 }, ... ] },
    { "name": "high",     "data": [...] },
    { "name": "medium",   "data": [...] },
    { "name": "low",      "data": [...] }
  ]
}
```

### 3.6 `GET /api/dashboard/vuln-distribution` — 🛠️ 待开发

**响应 200**
```json
{
  "buckets": [
    { "name": "注入",        "category": "injection",          "count": 34 },
    { "name": "认证缺陷",    "category": "auth",               "count": 28 },
    { "name": "XSS",         "category": "xss",                "count": 22 },
    { "name": "配置错误",    "category": "misconfig",          "count": 14 },
    { "name": "敏感数据暴露","category": "exposure",           "count": 9  },
    { "name": "其他",        "category": "other",              "count": 6  }
  ]
}
```

可选参数：`?group_by=owasp|category|severity`。

### 3.7 `GET /api/dashboard/asset-cluster` — 🛠️ 待开发

**响应 200**
```json
{
  "clusters": [
    { "system": "CRM",    "high": 3, "medium": 8, "low": 22 },
    { "system": "ERP",    "high": 1, "medium": 5, "low": 14 },
    { "system": "官网",   "high": 2, "medium": 3, "low": 18 },
    { "system": "OA",     "high": 0, "medium": 4, "low": 9  },
    { "system": "支付",   "high": 4, "medium": 6, "low": 5  },
    { "system": "大数据", "high": 1, "medium": 2, "low": 11 },
    { "system": "BI",     "high": 0, "medium": 1, "low": 7  },
    { "system": "内部工具","high": 0, "medium": 3, "low": 17 }
  ]
}
```

### 3.8 `GET /api/reports` — 🛠️ 待开发（列表）

**查询参数**：`?range=7d&type=&status=&limit=50&offset=0`

**响应 200**
```json
{
  "items": [
    {
      "id": "RPT-2026-0509-014",
      "title": "DC-IDC-A 段月报",
      "type": "compliance_monthly",
      "critical_count": 7,
      "status": "published|pending_review|editing|archived",
      "created_at": "2026-05-09T08:00:00+08:00",
      "author": "shan",
      "scan_id": "01JS..."
    }
  ],
  "total": 28
}
```

### 3.9 `GET /api/events?since=...&limit=50` — 🛠️ 待开发

**响应 200**
```json
{
  "items": [
    {
      "id": "evt-...",
      "timestamp": "2026-05-09T12:38:04+08:00",
      "level": "critical|warning|info|ok",
      "source": "weak_password|port_scan|asset_discovery|report|orchestrator",
      "task_id": "TASK-2026-0509-014",
      "message": "10.0.4.21:22 命中弱口令字典 — root/admin123"
    }
  ]
}
```

首屏轮询/SSE，WS 连接后切换为 `event:"activity_event"` 实时推送（同 2.15）。

---

## 4 · 任务详情 `04-task-detail.html`

| # | 功能点 | 方法 | 路径 | 状态 |
|---|--------|------|------|------|
| 4.1 | 获取任务详情（头部、KPI、进度） | `GET` | `/api/scans/{task_id}` | 🛠️ 待开发 |
| 4.2 | 暂停任务 | `POST` | `/api/scans/{task_id}/pause` | 🛠️ 待开发 |
| 4.3 | 恢复任务 | `POST` | `/api/scans/{task_id}/resume` | 🛠️ 待开发 |
| 4.4 | 终止任务 | `POST` | `/api/scans/{task_id}/cancel` | 🛠️ 待开发 |
| 4.5 | 基于当前任务生成报告 | `POST` | `/api/scans/{task_id}/reports` | 🛠️ 待开发 |
| 4.6 | 资产列表（Tab-资产视图） | `GET` | `/api/scans/{task_id}/assets` | 🛠️ 待开发 |
| 4.7 | 资产搜索/筛选/排序 | `GET` | `/api/scans/{task_id}/assets?q=&risk=&sort=` | 🛠️ 待开发（在 4.6 参数基础上扩展） |
| 4.8 | 资产详情（右侧面板） | `GET` | `/api/assets/{asset_id}` | 🛠️ 待开发 |
| 4.9 | 资产开放端口指纹 | `GET` | `/api/assets/{asset_id}/services` | 🛠️ 待开发 |
| 4.10 | 资产漏洞列表 | `GET` | `/api/assets/{asset_id}/vulnerabilities` | 🛠️ 待开发 |
| 4.11 | 对单资产深度扫描 | `POST` | `/api/assets/{asset_id}/deep-scan` | 🛠️ 待开发 |
| 4.12 | 扫描日志（Tab-扫描日志） | `GET` | `/api/scans/{task_id}/logs?level=&tail=300` | 🛠️ 待开发 |
| 4.13 | 智能体思维链（Tab-思维链） | `GET` | `/api/scans/{task_id}/activities?type=thought` | 🛠️ 待开发 |
| 4.14 | 任务报告列表（Tab-报告） | `GET` | `/api/scans/{task_id}/reports` | 🛠️ 待开发 |
| 4.15 | 智能体活动黑板数据 | `GET` + WS | `/api/scans/{task_id}/blackboard` + `event:"blackboard_update"` | 🛠️ 待开发 |
| 4.16 | 高危操作 — 提出确认 | WS | `event:"high_risk_confirm"` (server→client) | 🛠️ 待开发 |
| 4.17 | 高危操作 — 回复决策 | `POST` | `/api/high-risk-confirms/{confirm_id}/decide` | 🛠️ 待开发 |
| 4.18 | 任务级实时推送（进度、日志、活动） | WS | `event:"task_update"` / `log_append` / `activity_event` | 🛠️ 待开发 |
| 4.19 | 暂停/清空日志流（前端本地） | — | — | N/A |
| 4.20 | 黑板事件分页查询（历史回放） | `GET` | `/api/scans/{task_id}/blackboard/events?since=&limit=&type=` | 🛠️ 待开发 |
| 4.21 | 黑板事件复杂筛选 | `POST` | `/api/scans/{task_id}/blackboard/query` | 🛠️ 待开发 |
| 4.22 | 黑板单事件实时推送 | WS | `event:"blackboard_event"`（单事件，对齐产品文档 §7.6.3） | 🛠️ 待开发 |
| 4.23 | 任务维度 Finding 列表（统一风险入口） | `GET` | `/api/scans/{task_id}/findings?category=&severity=&limit=&offset=` | 🛠️ 待开发 |
| 4.24 | Finding 详情（含 evidence_refs） | `GET` | `/api/findings/{finding_id}` | 🛠️ 待开发 |
| 4.25 | 证据文件下载（对应产品文档 §7.5.4） | `GET` | `/api/evidences/{evidence_id}` | 🛠️ 待开发 |

### 4.1 `GET /api/scans/{task_id}` — 🛠️ 待开发

**响应 200**
```json
{
  "task_id": "TASK-2026-0509-014",
  "scan_id": "01JS0...ULID",
  "status": "running|queued|awaiting_user|completed|failed|cancelled|paused",
  "target": "192.168.1.0/24",
  "description": "orchestrator 调度 4 个智能体并行执行…",
  "scope": { "ports": "22,3389,445,3306", "agents": ["..."] },
  "progress": { "percent": 0.68, "scanned": 173, "total": 254 },
  "kpi": {
    "discovered_assets": 47,
    "open_ports": 183,
    "critical_findings": 3,
    "medium_findings": 11,
    "elapsed_seconds": 222
  },
  "started_at": "2026-05-09T12:34:22+08:00",
  "finished_at": null,
  "actor_id": "shan",
  "created_at": "..."
}
```

### 4.2 – 4.4 任务生命周期

- `POST /api/scans/{task_id}/pause` → `{ "task_id": "...", "status": "paused" }`
- `POST /api/scans/{task_id}/resume` → `{ "task_id": "...", "status": "running" }`
- `POST /api/scans/{task_id}/cancel` → `{ "task_id": "...", "status": "cancelled" }`

状态枚举与 `cmdb/models.py::VALID_SCAN_STATUSES`（`queued/running/awaiting_user/completed/failed/cancelled`）保持一致，新增 `paused`。

### 4.5 `POST /api/scans/{task_id}/reports` — 🛠️ 待开发

**请求**
```json
{ "format": "pdf|markdown|json", "include_sections": ["summary","assets","vulnerabilities","timeline"] }
```

**响应 202**
```json
{ "report_id": "RPT-2026-0509-014", "status": "generating", "download_url": null }
```

### 4.6 `GET /api/scans/{task_id}/assets` — 🛠️ 待开发

**查询参数**：`q`（IP/主机名）、`risk=critical,high`、`sort=ip|risk|discovered_at`、`limit`、`offset`

**响应 200**
```json
{
  "items": [
    {
      "asset_id": 1021,
      "ip": "192.168.1.21",
      "hostname": "db-master-01",
      "os": "Ubuntu 22.04",
      "open_ports": [22, 3306, 6379],
      "risk": "critical|high|medium|low|safe",
      "discovered_at": "2026-05-09T12:37:22+08:00"
    }
  ],
  "total": 47
}
```

### 4.8 – 4.10 资产详情簇

- `GET /api/assets/{asset_id}` — 基础属性 + 业务分类 + 标签
- `GET /api/assets/{asset_id}/services` — 端口指纹（port/protocol/service/product/version/state/risk），映射 `cmdb/models.py::Service`
- `GET /api/assets/{asset_id}/vulnerabilities` — 漏洞列表（severity/category/title/cve_id/evidence/raw_log_path/discovered_by），映射 `Vulnerability`

### 4.11 `POST /api/assets/{asset_id}/deep-scan` — 🛠️ 待开发

**请求**
```json
{ "agents": ["vuln_scan","weak_password"], "priority": "high" }
```
**响应 201**：同 3.1（返回新 `task_id`）。

### 4.12 `GET /api/scans/{task_id}/logs` — 🛠️ 待开发

**查询参数**：`level=critical,warning,info,ok`、`tail=300`、`since=<timestamp>`

**响应 200**
```json
{
  "items": [
    { "timestamp": "...", "level": "critical", "source": "weak_password", "message": "..." }
  ]
}
```

### 4.13 `GET /api/scans/{task_id}/activities?type=thought|tool_call|tool_result`

字段：`agent` / `step` / `input` / `output` / `duration_ms` / `timestamp`。

### 4.15 `GET /api/scans/{task_id}/blackboard` — 🛠️ 待开发

**响应 200**
```json
{
  "updated_at": "...",
  "agents": [
    { "name": "asset_discovery", "status": "done",     "progress": 1.00, "elapsed_seconds": 84,  "note": "47/254 alive" },
    { "name": "port_scan",       "status": "running",  "progress": 0.68, "eta_seconds": 135, "note": "扫描中：192.168.1.173" },
    { "name": "weak_password",   "status": "running",  "progress": 0.24, "hits": 2,   "note": "剩余 8 主机" },
    { "name": "vuln_scan",       "status": "queued" }
  ],
  "stats": { "discovered_assets": 47, "open_ports": 183, "critical_findings": 3 }
}
```

### 4.16 WebSocket `high_risk_confirm`（Server→Client） — 🛠️ 待开发

```json
{
  "event": "high_risk_confirm",
  "confirm_id": "hrc-...",
  "task_id": "TASK-2026-0509-014",
  "agent": "vuln_scan",
  "asset": { "ip": "192.168.1.21", "hostname": "db-master-01" },
  "action": "sql_injection_probe",
  "impact": "可能影响业务",
  "deadline": "2026-05-09T12:40:00+08:00"
}
```

### 4.17 `POST /api/high-risk-confirms/{confirm_id}/decide` — 🛠️ 待开发

**请求**
```json
{ "decision": "approve|reject", "note": "白名单环境允许执行" }
```

**响应 200**
```json
{ "confirm_id": "...", "decision": "approve", "decided_by": "shan", "decided_at": "..." }
```

### 4.18 WebSocket `task_update`（Server→Client） — 🛠️ 待开发

```json
{
  "event": "task_update",
  "task_id": "...",
  "status": "running",
  "progress": { "percent": 0.71, "scanned": 180, "total": 254 },
  "kpi": { "discovered_assets": 51, "critical_findings": 4 },
  "timestamp": "..."
}
```

`log_append` 同类结构，`items` 为 4.12 的单条日志。

### 4.20 `GET /api/scans/{task_id}/blackboard/events` — 🛠️ 待开发

**查询参数**：`since=<ISO 8601>`、`limit=100`、`type=asset.discovered,service.discovered,fingerprint.discovered,finding.*`

**响应 200**（事件结构严格对齐产品文档 §7.6.3）
```json
{
  "items": [
    {
      "event_id": "evt-001",
      "task_id": "TASK-2026-0509-014",
      "type": "asset.discovered",
      "producer_agent": "asset_discovery",
      "created_at": "2026-05-09T12:38:02+08:00",
      "confidence": 0.92,
      "data": { "asset_type": "domain", "value": "api.example.com", "in_scope": true },
      "evidence_refs": ["evidence-001"],
      "tags": ["asset", "domain"]
    }
  ],
  "next_since": "2026-05-09T12:38:02.457+08:00",
  "total": 1284
}
```

### 4.21 `POST /api/scans/{task_id}/blackboard/query` — 🛠️ 待开发

**请求**（对齐产品文档 §11.4）
```json
{
  "event_types": ["asset.discovered", "service.discovered"],
  "filters": { "data.in_scope": true, "confidence_gte": 0.8 },
  "time_range": { "from": "...", "to": "..." },
  "limit": 100
}
```

**响应 200**：同 4.20 结构。

### 4.22 WebSocket `blackboard_event`（Server→Client） — 🛠️ 待开发

**与 2.14 `blackboard_update`（聚合帧）的区别**：本事件是**单条黑板事件**推送，粒度对齐产品文档 §7.6.3 事件模型；`blackboard_update` 只传 stats 聚合。两者并存，前端按需订阅。

```json
{
  "event": "blackboard_event",
  "chat_id": "...",
  "task_id": "TASK-2026-0509-014",
  "payload": {
    "event_id": "evt-001",
    "type": "finding.high_risk",
    "producer_agent": "weak_password",
    "created_at": "...",
    "confidence": 0.91,
    "data": { "asset_id": 1021, "risk_level": "critical", "title": "SSH 弱口令" },
    "evidence_refs": ["evidence-778"]
  }
}
```

### 4.23 `GET /api/scans/{task_id}/findings` — 🛠️ 待开发

**查询参数**：`category=cve|weak_password|misconfig|exposure`、`severity=critical,high`、`status=open|verified|false_positive`、`limit`、`offset`

**响应 200**（字段对齐产品文档 §10.6 findings 表）
```json
{
  "items": [
    {
      "finding_id": "finding-001",
      "title": "Nginx 版本存在已知漏洞风险",
      "finding_type": "vulnerability",
      "category": "cve",
      "risk_level": "medium",
      "asset_id": 1021,
      "service_id": 2044,
      "confidence": 0.76,
      "status": "open",
      "cve_id": "CVE-XXXX-XXXX",
      "discovered_by": "vuln_scan",
      "created_at": "..."
    }
  ],
  "total": 47
}
```

### 4.24 `GET /api/findings/{finding_id}` — 🛠️ 待开发

**响应 200**
```json
{
  "finding_id": "finding-001",
  "title": "Nginx 版本存在已知漏洞风险",
  "category": "cve",
  "risk_level": "medium",
  "asset": { "asset_id": 1021, "ip": "192.168.1.21", "hostname": "db-master-01" },
  "service": { "port": 443, "service": "nginx", "version": "1.20.2" },
  "cve_id": "CVE-XXXX-XXXX",
  "confidence": 0.76,
  "description": "...",
  "impact": "该服务对公网开放，版本命中漏洞范围",
  "recommendation": "升级到官方修复版本，并复查相关配置。",
  "evidence_refs": ["evidence-001", "evidence-002"],
  "discovered_by": "vuln_scan",
  "created_at": "...",
  "updated_at": "..."
}
```

### 4.25 `GET /api/evidences/{evidence_id}` — 🛠️ 待开发

**响应 200**：直接返回二进制（截图/响应包/工具输出 JSON），`Content-Type` 按证据类型动态；或返回短期下载 URL：
```json
{ "download_url": "/api/media/xxx/evidence-001.json", "sha256": "...", "expires_at": "..." }
```

---

## 5 · 设置 `05-settings.html`

| # | 功能点 | 方法 | 路径 | 状态 |
|---|--------|------|------|------|
| 5.4 | 获取设置 | `GET` | `/api/settings` | ✅ 已存在 |
| 5.5 | 更新设置（主题/语言/时区/动效） | `GET/PUT` | `/api/settings/update` | 🔧 待扩展 |
| 5.6 | 模型提供方列表 | `GET` | `/api/providers` | 🛠️ 待开发 |
| 5.7 | 探测提供方可用模型 | `GET` | `/api/settings/models?api_base=...` | ✅ 已存在 |
| 5.8 | 新增提供方 | `POST` | `/api/providers` | 🛠️ 待开发 |
| 5.9 | 更新提供方配置 | `PUT` | `/api/providers/{id}` | 🛠️ 待开发 |
| 5.10 | 删除提供方 | `DELETE` | `/api/providers/{id}` | 🛠️ 待开发 |
| 5.11 | 设为默认提供方 | `POST` | `/api/providers/{id}/default` | 🛠️ 待开发 |
| 5.12 | 通知偏好读取/写入 | `GET/PUT` | `/api/settings/notifications` | 🛠️ 待开发 |
| 5.16 | 危险区 — 退出登录 | `POST` | `/api/auth/logout` | 🛠️ 待开发（同 1.3） |
| 5.17 | 危险区 — 清空所有会话 | `DELETE` | `/api/sessions?all=true` | 🛠️ 待开发 |
| 5.19 | 平台能力概览 — 工具列表（只读） | `GET` | `/api/tools` | 🛠️ 待开发（对齐 PRD R7.5） |

### 5.19 `GET /api/tools` — 🛠️ 待开发

**响应 200**（对齐产品文档 §7.5.2 Tool Manifest 摘要）
```json
{
  "items": [
    {
      "name": "port_scanner_safe",
      "display_name": "安全端口扫描工具",
      "version": "1.0.0",
      "kind": "container",
      "risk_level": "medium",
      "allowed_in_agents": ["port_scan", "asset_discovery"],
      "requires_approval": false
    }
  ],
  "total": 14
}
```

> **仅只读**，不暴露 POST/PUT/DELETE。自定义 Tool 接入延后到 `gap/tool-policy.md`。

> 根据附录 B.2 决策，本章节**不含** `5.1 个人资料` / `5.2 更新档案` / `5.3 头像` / `5.13 安全与鉴权` / `5.14 阈值与限流` / `5.15 用户与角色` / `5.18 重置平台`（登录后统一 admin，无用户体系与分级管控）。

### 5.5 `/api/settings/update` — 🔧 待扩展

在现有 `model/provider/api_base/api_key` 基础上扩展：
```
?theme=ocean|cyan|green
?language=zh-CN|en-US
?timezone=Asia/Shanghai
?dark_mode=1
?animations=1
```
建议新增 `PUT /api/settings`（body 形式）作为未来主入口，保留 `GET /api/settings/update` 做兼容。

### 5.6 `GET /api/providers` — 🛠️ 待开发

**响应 200**
```json
{
  "items": [
    {
      "id": "prv-1",
      "name": "Anthropic",
      "kind": "anthropic|openai|ollama|azure|deepseek|custom",
      "model": "claude-3-5-sonnet",
      "api_base": "https://api.anthropic.com",
      "api_key_masked": "sk-***45f8",
      "status": "online|offline|unknown",
      "is_default": true,
      "created_at": "...",
      "updated_at": "..."
    }
  ]
}
```

### 5.8 `POST /api/providers` — 🛠️ 待开发

**请求**
```json
{ "name": "OpenAI", "kind": "openai", "model": "gpt-4o", "api_base": "https://api.openai.com/v1" }
```
`api_key` 通过 `X-Settings-Api-Key` 请求头传。

**响应 201**：同 5.6 列表项结构 + `restart_required: true`（若需要）。

### 5.12 `/api/settings/notifications` — 🛠️ 待开发

**GET 响应 / PUT 请求**
```json
{
  "critical_vuln": true,
  "task_complete": true,
  "high_risk_confirm": true,
  "email_summary": false,
  "email_summary_cron": "0 8 * * 1"
}
```

### 5.17 `DELETE /api/sessions?all=true` — 🛠️ 待开发

**响应 200**
```json
{ "deleted_count": 23, "cleared_blackboard": true }
```

---

## 6 · 汇总对比

### 6.1 已有可直接复用（5 个）

| # | 接口 | 用于页面 |
|---|------|---------|
| A1 | `GET /health` | 基建 |
| A2 | `GET /v1/models` / `POST /v1/chat/completions` | 02-home 对话、附件 |
| A3 | `GET /api/sessions` / `GET /api/sessions/{key}/messages` / `GET /api/sessions/{key}/delete` | 02-home 会话历史 |
| A4 | `GET /api/settings` / `GET /api/settings/update` / `GET /api/settings/models` | 05-settings |
| A5 | `GET /api/commands` | 02-home 快捷指令 |
| A6 | `GET /api/agents` (+skills CRUD) | 02-home 专家智能体 |
| A7 | WebSocket 协议（`ready/message/delta/stream_end/error`、`new_chat/attach/message/stop`） | 02-home、04-task-detail |

### 6.2 需扩展字段/参数（5 个）

| # | 接口 | 扩展内容 |
|---|------|---------|
| E1 | `GET /api/sessions` | 新增 `q/archived/limit/offset/total/message_count` |
| E2 | `GET /api/sessions/{key}/delete` | 建议新增 `DELETE /api/sessions/{key}` 别名，语义更标准 |
| E3 | `GET /api/agents` | 新增 `include_status=true` 返回 status/progress/heartbeat |
| E4 | `GET /api/settings/update` | 新增 `theme/language/timezone/dark_mode/animations` |
| E5 | `GET /api/auth/ws-token` | 现有 `tokenIssuePath` 映射并标准化为 `/api/auth/ws-token` |

### 6.3 全部待开发接口清单（约 38 项）

**认证（4）**
- 🛠️ `POST /api/auth/login`
- 🛠️ `GET /api/auth/whoami`
- 🛠️ `POST /api/auth/logout`
- 🛠️ `GET /api/auth/ws-token`（🔧 扩展自现有 tokenIssuePath）

**Dashboard / Home KPI（5）**
- 🛠️ `GET /api/dashboard/summary`
- 🛠️ `GET /api/dashboard/vuln-trend`
- 🛠️ `GET /api/dashboard/vuln-distribution`
- 🛠️ `GET /api/dashboard/asset-cluster`
- 🛠️ `POST /api/dashboard/snapshot`

**会话 / 通知（4）**
- 🛠️ `POST /api/sessions`（显式创建）
- 🛠️ `POST /api/sessions/{key}/archive`
- 🛠️ `DELETE /api/sessions?all=true`
- 🛠️ `GET/POST /api/notifications`（+ `/read` / `/read-all`）

**扫描任务（6）**
- 🛠️ `POST /api/scans`
- 🛠️ `GET /api/scans/{task_id}`
- 🛠️ `POST /api/scans/{task_id}/pause`
- 🛠️ `POST /api/scans/{task_id}/resume`
- 🛠️ `POST /api/scans/{task_id}/cancel`
- 🛠️ `POST /api/scans/{task_id}/reports`

**任务内数据（8）**
- 🛠️ `GET /api/scans/{task_id}/assets`
- 🛠️ `GET /api/scans/{task_id}/logs`
- 🛠️ `GET /api/scans/{task_id}/activities`
- 🛠️ `GET /api/scans/{task_id}/reports`
- 🛠️ `GET /api/scans/{task_id}/blackboard`（聚合快照）
- 🛠️ `GET /api/scans/{task_id}/blackboard/events`（事件分页，对齐产品文档 §7.6.3）
- 🛠️ `POST /api/scans/{task_id}/blackboard/query`（事件复杂筛选）
- 🛠️ `GET /api/events`

**Finding & Evidence（3，新增，对齐产品文档 §10.6 / §7.5.4）**
- 🛠️ `GET /api/scans/{task_id}/findings`（任务维度统一风险入口）
- 🛠️ `GET /api/findings/{finding_id}`
- 🛠️ `GET /api/evidences/{evidence_id}`

**资产（4）**
- 🛠️ `GET /api/assets/{asset_id}`
- 🛠️ `GET /api/assets/{asset_id}/services`
- 🛠️ `GET /api/assets/{asset_id}/vulnerabilities`
- 🛠️ `POST /api/assets/{asset_id}/deep-scan`

**Tool Registry 只读（1，新增）**
- 🛠️ `GET /api/tools`（对齐产品文档 §7.5）

**报告（2）**
- 🛠️ `GET /api/reports`
- 🛠️ `GET /api/reports/{report_id}`（详情/下载）

**高危确认（1）**
- 🛠️ `POST /api/high-risk-confirms/{confirm_id}/decide`

**提供方（6）**
- 🛠️ `GET /api/providers`
- 🛠️ `POST /api/providers`
- 🛠️ `PUT /api/providers/{id}`
- 🛠️ `DELETE /api/providers/{id}`
- 🛠️ `POST /api/providers/{id}/default`
- 🛠️ `GET/PUT /api/settings/notifications`

**管理员（1）**
- 🛠️ `GET /api/admin/audit-logs`（预留，PR7）

**WebSocket 扩展事件（6）**
- 🛠️ `event: "task_update"`
- 🛠️ `event: "blackboard_update"`（聚合帧）
- 🛠️ `event: "blackboard_event"`（单事件，对齐产品文档 §7.6.3）
- 🛠️ `event: "log_append"`
- 🛠️ `event: "activity_event"`
- 🛠️ `event: "high_risk_confirm"`

### 6.4 数量统计

| 状态 | 数量 |
|------|------|
| ✅ 已存在可直接复用 | ~12 个端点 |
| 🔧 已存在但需扩展 | ~5 个端点 |
| 🛠️ 待开发 REST | ~37 个端点（31 基线 + 6 项 R7 扩展：blackboard events/query + findings list/detail + evidence + tools） |
| 🛠️ 待开发 WebSocket 事件 | 6 类事件（原 5 类 + `blackboard_event`） |

> 已按附录 B.2 决策删除：`/api/users/me`、`/api/users/me/avatar`、`/api/admin/security`、`/api/admin/limits`、`/api/admin/users[/(id)]`、`/api/admin/factory-reset`。
> 已按 PRD R7 决策新增：黑板事件粒度 API、Finding 统一查询、Evidence 下载、Tool Registry 只读。

---

## 附录 A · 现有后端接口规范（摘录）

### A.1 HTTP 端点（aiohttp + websockets 混合）

**通过 `secbot/api/server.py::app.router` 注册：**
```
POST /v1/chat/completions
GET  /v1/models
GET  /health
```

**通过 `secbot/api/agents.py` 注册：**
```
GET/POST             /api/agents
GET/PUT/DELETE       /api/agents/{name}
GET/POST             /api/skills
GET/PUT/DELETE       /api/skills/{name}
```

**通过 `secbot/channels/websocket.py` 的 HTTP fallback 处理（非 aiohttp 路由）：**
```
GET /api/sessions
GET /api/sessions/{key}/messages
GET /api/sessions/{key}/delete
GET /api/settings
GET /api/settings/update
GET /api/settings/models
GET /api/commands
GET /api/media/{sig}/{payload}
```

> ⚠️ 本次重构建议将所有 `/api/**` 路由统一迁移到 aiohttp router 下，避免 websockets 库 HTTP 解析器的局限（当前只支持 GET，无 body）。

### A.2 数据模型（`secbot/cmdb/models.py`）

- `Scan(id:ULID, target, status, scope_json, started_at, finished_at, error, actor_id)`
- `Asset(id, scan_id, target, ip, hostname, os_guess, tags, actor_id, created_at, updated_at)`
- `Service(id, asset_id, port, protocol, service, product, version, state)`
- `Vulnerability(id, asset_id, service_id, severity, category, title, cve_id, evidence, raw_log_path, discovered_by)`

枚举：
- `VALID_SCAN_STATUSES = {queued, running, awaiting_user, completed, failed, cancelled}`
- `VALID_SEVERITIES = {critical, high, medium, low, info}`
- `VALID_VULN_CATEGORIES = {cve, weak_password, misconfig, exposure}`

### A.3 WebSocket 协议（`docs/websocket.md`）

详见章节 0.7。事件命名 snake_case，每帧必含 `event` 字段，Token 走查询参数 `?token=`。

---

## 附录 B · 风险与建议（已决策）

### B.1 路由策略（R1） ✅ 已定

**决策**：**新接口原生走 aiohttp，老接口不动**。

- `secbot/channels/websocket.py` 的 HTTP fallback 受 websockets 库限制（硬校验 `method == GET`、无 body），详见 L598 注释。
- 所有新增写接口（`/api/auth/*`、`/api/scans/*`、`/api/assets/*`、`/api/dashboard/*`、`/api/reports/*`、`/api/notifications/*`、`/api/admin/*`）在 `secbot/api/server.py` 内 aiohttp 路由注册，原生支持 `POST/PUT/DELETE` + JSON body。
- 老接口保持不动：`/api/sessions/**`（含 `/delete` hack）、`/api/settings/**`（含 `X-Settings-Api-Key`）、`/api/commands`、`/api/media/**` 保留在 websockets fallback。
- **写操作 + WebSocket 跟进** 模式：`POST /api/scans` → 返回 `task_id` → 前端订阅 `/ws/ops` 接收 `task_update` / `log_append` / `activity_event` 等推送。

**工作量**：~0 行迁移（老接口不碰），仅新建 aiohttp 路由模块。

### B.2 认证链路（R2） ✅ 已定

- **1.1 登录**：任意非空 `shared_secret` 即可登录（不校验值，仅校验非空）→ 签发会话 Token（JWT，24h 过期，不续签）。
- **1.2 whoami**：❌ 不做，登录后一律视为 admin。
- **1.3 logout**：保留，清除服务端 session 标记。
- **1.4 ws-token**：保留（WebSocket 鉴权用）。
- **Token 存储**：localStorage（与现有前端实践一致，并便于 WS 查询参数传递）。
- **操作者识别**：登录请求体携带 `operator_name`（可选昵称，写入 token claims + 审计日志）；未填则记为 `admin`。
- **§5.4 用户管理**：❌ 删除整节（既然全部 admin，无分级）；05-settings.html「用户与角色」Tab 同步下线。

### B.3 CMDB 控制器（R3） ✅ 已定

- **聚合查询**：MVP 先 SQL 直查（`/api/dashboard/kpis` 等），Repo 层加必要索引；后续再评估缓存。
- **报告导出**（`POST /api/scans/{id}/reports`）：异步任务模式，立即返回 `report_id` + 状态轮询；复用 `secbot/report/` 现有异步能力。
- **分页**：所有列表接口强制分页，默认 `limit=20, offset=0`，最大 `limit=200`；响应封装 `{items, total, limit, offset}`（对齐 §0.5）。

### B.4 WebSocket 事件（R4） ✅ 已定

- **双连接分离**：
  - `/ws/chat/{session_id}` — 保留现有对话流（`ready/attached/message/delta/...`）
  - `/ws/ops` — 新增运维流（`task_update / log_append / activity_event / high_risk_confirm / dashboard_tick`）
- **订阅语义**：`/ws/ops` 首帧由客户端发送 `{event:"subscribe", scope:"task:<id>"|"dashboard"|"activity"}`，服务端按 scope 过滤推送。
- **鉴权**：两条 WS 都走 `?token=...` 查询参数。

### B.5 前端 Mock 策略（R5） ✅ 已定

- `VITE_USE_MOCK=true` 时使用 `webui/src/mocks/*.json` fixture；生产构建强制关闭。
- Mock 数据必须符合 §0 规范（ISO 8601 时间戳、错误结构 `{error}`、分页结构 `{items,total,limit,offset}`）。
- 每个 PR 落地一批后端接口后，对应的前端立即替换真实 HTTP 客户端，避免 Mock 长期存在造成漂移。

---

## 附录 C · 推荐开发顺序（与 PR 计划对齐）

| PR | 后端工作 | 前端对应 |
|----|---------|---------|
| PR1 | aiohttp 新路由骨架 + `/api/auth/*`（非空密钥登录/JWT/logout/ws-token） | 登录页接线 |
| PR2 | `/api/dashboard/*` + KPI 聚合查询 | Dashboard Mock→Real |
| PR3 | `/api/scans/*` + CMDB 控制器 + **`/api/scans/{id}/findings`**（R7.4） + **黑板事件 API**（R7.3） | TaskDetail Mock→Real，含「黑板 Tab」事件流 |
| PR4 | `/api/assets/*` + `/api/reports/*` + **`/api/findings/{id}`** + **`/api/evidences/{id}`**（R7.4） | TaskDetail 资产面板 / Reports 页 / 证据查看 |
| PR5 | WebSocket 扩展事件 **6 类**（含 `blackboard_event` 单事件，R7.3） + `/api/high-risk-confirms/*`（R7.7） | 实时流 + 思维链 + 黑板事件 + 高危确认 |
| PR6 | `/api/providers/*` + `/api/settings/notifications` + **`GET /api/tools`**（R7.5） | Settings Tab：模型与提供方 / 通知与推送 / 平台能力 |
| PR7 | `/api/admin/audit-logs`（审计日志仅读，不含用户管理/重置） | 管理员专用面板（等效 Tab） |

---

**文档结束** · 风险 R1–R5 已决策锁定，待用户最终确认 🛠️ 待开发项进入实施排期。

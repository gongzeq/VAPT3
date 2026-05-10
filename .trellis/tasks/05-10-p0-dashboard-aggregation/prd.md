# P0 · Dashboard Aggregation & Agent Runtime Status

> Parent: [05-10-backend-api-gap-fill](../05-10-backend-api-gap-fill/prd.md)
> Priority: P0 · Est: 3–4d

## Goal

交付 Dashboard 大屏 6 个 KPI、2 个饼图、1 条趋势折线、1 个资产聚类柱图的聚合接口；扩展 `/api/agents` 返回运行时状态；补齐 WS `task_update` / `blackboard_update` 事件。完成后前端 `data/mock/dashboard.ts` 除 `recentReports` 以外可全量替换为真实接口。

## Requirements

### HTTP 接口（6 个）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/dashboard/summary` | GET | 聚合 6 个 KPI，字段见 §Contract.1 |
| `/api/dashboard/vuln-trend?range=7d\|30d\|90d` | GET | 按日 × severity 分组 |
| `/api/dashboard/vuln-distribution` | GET | 按 category 分组 |
| `/api/dashboard/asset-distribution` | GET | 按 `asset.tags.type` 分组 |
| `/api/dashboard/asset-cluster` | GET | 按 `asset.tags.system` × severity 聚类 |
| `/api/agents?include_status=true` | GET | 现有端点扩展，追加 runtime 字段 |

### WebSocket 事件（2 个）

| 事件 | 说明 | 触发时机 |
|------|------|----------|
| `task_update` | 扫描状态/进度/KPI 变化 | Scan 状态转移 + 每 N 秒进度上报 |
| `blackboard_update` | 聚合统计增量 | 资产/端口/漏洞新增 |

### CMDB 模型变更

- `Vulnerability.category` 枚举新增：`injection`, `auth`, `xss`, `other`（扩展 `VALID_VULN_CATEGORIES`）
- `Asset.tags` 约定：资产发现 agent 写入 `{"system": "<业务系统>", "type": "web_app|api|database|server|network|other"}`（详见 `.trellis/spec/backend/cmdb-schema.md` §2.1）
- 无新增表 / 无新增列

## Contracts

### 1. `GET /api/dashboard/summary`

响应字段严格对齐前端 `kpiCards[]`（6 项，**不含合规等级**）：

```json
{
  "active_tasks":       { "value": 12,  "delta": 3  },
  "completed_scans":    { "value": 847, "delta": 24 },
  "critical_vuln":      { "value": 36,  "delta": -5 },
  "asset_total":        { "value": 1204,"delta": 18 },
  "pending_alerts":     { "value": 9,   "delta": 2  },
  "agents_online":      { "value": 5,   "delta": 0  },
  "generated_at": "2026-05-10T12:38:00+08:00"
}
```

- `delta` = `current - 24h_ago`，整数。
- 聚合 SQL 参考：
  - `active_tasks` = `COUNT(scan) WHERE status IN ('queued','running','awaiting_user')`
  - `completed_scans` = `COUNT(scan) WHERE status='completed'`
  - `critical_vuln` = `COUNT(vulnerability) WHERE severity='critical'`
  - `asset_total` = `COUNT(asset)`
  - `pending_alerts` = `COUNT(vulnerability) WHERE severity IN ('critical','high') AND NOT acknowledged`（若无字段，本期等同 critical_vuln）
  - `agents_online` = `SubagentManager.count(status in {'idle','running'})`

### 2. `GET /api/dashboard/vuln-trend?range=7d|30d|90d`

```json
{
  "range": "30d",
  "series": [
    { "name": "critical", "data": [{"date":"2026-04-10","count":2}, ...] },
    { "name": "high",     "data": [...] },
    { "name": "medium",   "data": [...] },
    { "name": "low",      "data": [...] }
  ]
}
```

- 时间单位：按天（UTC+8 日界），使用 `DATE(created_at, 'localtime')` 分组。
- `range` 参数：`7d` → 最近 7 天；`30d` → 30 天；`90d` → 90 天。
- 无漏洞的日期以 `count=0` 占位（前端要求连续）。

### 3. `GET /api/dashboard/vuln-distribution`

```json
{
  "buckets": [
    { "category": "injection", "name": "注入",         "count": 34 },
    { "category": "auth",      "name": "认证缺陷",     "count": 28 },
    { "category": "xss",       "name": "XSS",          "count": 22 },
    { "category": "misconfig", "name": "配置错误",     "count": 14 },
    { "category": "exposure",  "name": "敏感数据暴露", "count": 9  },
    { "category": "other",     "name": "其他",         "count": 6  }
  ]
}
```

- `name` 固定中文，由后端返回（避免前端依赖多语言字典）。
- `cve` / `weak_password` 属于既有枚举，本期保留但不在主分布中呈现；如扫描产生时，前端可自行归为 `其他`。

### 4. `GET /api/dashboard/asset-distribution`

```json
{
  "buckets": [
    { "type": "web_app",  "name": "Web 应用",  "count": 412 },
    { "type": "api",      "name": "API 端点",  "count": 268 },
    { "type": "database", "name": "数据库",    "count": 124 },
    { "type": "server",   "name": "服务器",    "count": 198 },
    { "type": "network",  "name": "网络设备",  "count": 86  },
    { "type": "other",    "name": "其他",      "count": 116 }
  ]
}
```

- 数据源：`asset.tags->>'type'`（JSON extract）；为 NULL 归为 `other`。

### 5. `GET /api/dashboard/asset-cluster`

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

- 分组键：`asset.tags->>'system'`；为 NULL 的资产不计入（后端以 warning 日志记录）。
- 每个 system 下统计关联漏洞 `severity` 计数（通过 `vulnerability.asset_id` join）。

### 6. `GET /api/agents?include_status=true`

现有响应字段基础上追加：

```json
{
  "agents": [
    {
      "name": "asset_discovery",
      "display_name": "资产发现智能体",
      "description": "...",
      "scoped_skills": [...],
      "status": "idle|running|queued|offline",
      "current_task_id": "TASK-2026-0510-014",
      "progress": 0.68,
      "last_heartbeat_at": "2026-05-10T12:38:00+08:00"
    }
  ]
}
```

- `status` 源自 `SubagentManager`；找不到记录时回落为 `offline`。
- `progress` 仅在 `running` 时有值，其它状态为 `null`。
- 不带 `include_status=true` 时保持现有响应形态，向后兼容。

### 7. WS `task_update`

```json
{
  "event": "task_update",
  "task_id": "TASK-2026-0510-014",
  "scan_id": "01JS...",
  "status": "running",
  "progress": 0.68,
  "kpi": { "discovered_assets": 47, "open_ports": 183, "critical_findings": 3 },
  "timestamp": "..."
}
```

- 广播粒度：每个 `chat_id` 订阅所属 scan；节流 1s。

### 8. WS `blackboard_update`

```json
{
  "event": "blackboard_update",
  "chat_id": "0e1b...c8",
  "stats": { "discovered_assets": 47, "open_ports": 183, "critical_findings": 3 },
  "timestamp": "..."
}
```

## Acceptance Criteria

- [ ] 5 个 Dashboard REST 端点在 `secbot/channels/websocket.py` 注册；请求返回结构与上述契约字节级一致。
- [ ] 无数据场景：所有端点返回 `200` 且业务字段为空数组 / 零值（不报 500）。
- [ ] `/api/agents?include_status=true` 向后兼容：不带参数时响应与现有版本一致。
- [ ] `Vulnerability` 的 `category` 接受新值 `injection/auth/xss/other`，现有数据迁移不需要改写。
- [ ] WS `task_update` 在 Scan 状态变更时至少触发一次；`blackboard_update` 在资产/漏洞增量时触发。
- [ ] 单元测试：
  - `tests/api/test_dashboard.py` 覆盖 5 个 REST 端点 happy path + 空数据 edge case。
  - `tests/cmdb/test_vulnerability_categories.py` 验证新枚举接受。
  - `tests/channels/test_ws_task_update.py` 验证事件推送。
- [ ] 前端 `webui/src/data/mock/dashboard.ts` 中的 `kpiCards / riskTrend* / assetDistribution / vulnDistribution / assetCluster` 全部切换为 hooks；`recentReports` 暂保留 mock。

## Out of Scope

- `report_meta` 表 & `/api/reports`（P1）。
- `/api/notifications` 通知中心（P2）。
- Agent 状态持久化（本期仅内存）。
- 合规等级字段。

## Technical Notes

- Spec：
  - `.trellis/spec/backend/cmdb-schema.md`（需更新）
  - `.trellis/spec/backend/dashboard-aggregation.md`（新增）
- 主文件：
  - `secbot/cmdb/repo.py` — 新增聚合函数
  - `secbot/api/agents.py` — 扩展 include_status
  - `secbot/channels/websocket.py` — 新端点路由 + WS 事件广播
  - `secbot/cmdb/models.py` — `VALID_VULN_CATEGORIES` 扩展

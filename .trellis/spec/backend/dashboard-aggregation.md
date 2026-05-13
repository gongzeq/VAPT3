# Dashboard Aggregation

> Authoritative contract for dashboard aggregation endpoints (`/api/dashboard/*`) and `/api/agents?include_status=true`.
> Implementation: `secbot/cmdb/repo.py` aggregation helpers + `secbot/channels/websocket.py` HTTP handlers.

---

## 1. Overview

Dashboard endpoints return pre-aggregated numbers computed on demand against the CMDB (`asset`, `service`, `vulnerability`, `scan` tables) plus the in-memory `SubagentManager`. No materialised views; every call runs fresh SQL.

Shared rules:

- **Read-only.** Dashboard handlers MUST NOT insert/update any CMDB row.
- **`actor_id` scoped.** Every query filters by the caller's `actor_id` (currently always `'local'`).
- **Timezone.** All time bucketing uses the server's local timezone (configured as UTC+8 for secbot). Date strings in responses are `YYYY-MM-DD`.
- **Pre-fill.** Trend endpoints return a dense series (no gaps); dates with zero rows are still emitted with `count=0`.
- **No caching (v1).** Results are recomputed per request. If latency becomes a concern, introduce a 5–10s in-process LRU cache keyed by `(actor_id, endpoint, query)` — not per-row DB caching.
- **Response shape.** Bare objects, per [api-design §0.3]. No outer `data` wrapper.

---

## 2. Endpoint contracts

### 2.1 `GET /api/dashboard/summary`

Response fields (all integers unless noted):

```json
{
  "active_tasks":    { "value": 12,  "delta": 3  },
  "completed_scans": { "value": 847, "delta": 24 },
  "critical_vuln":   { "value": 36,  "delta": -5 },
  "asset_total":     { "value": 1204,"delta": 18 },
  "pending_alerts":  { "value": 9,   "delta": 2  },
  "agents_online":   { "value": 5,   "delta": 0  },
  "generated_at":    "2026-05-10T12:38:00+08:00"
}
```

| Metric | Source | Query |
|--------|--------|-------|
| `active_tasks.value` | `scan` | `COUNT(*) WHERE status IN ('queued','running','awaiting_user')` |
| `completed_scans.value` | `scan` | `COUNT(*) WHERE status='completed'` |
| `critical_vuln.value` | `vulnerability` | `COUNT(*) WHERE severity='critical'` |
| `asset_total.value` | `asset` | `COUNT(*)` |
| `pending_alerts.value` | `vulnerability` | `COUNT(*) WHERE severity IN ('critical','high')` |
| `agents_online.value` | `SubagentManager` | `len([a for a in manager.list() if a.status in {'idle','running'}])` |
| `*.delta` | same table | same filter restricted to `created_at >= now-48h AND created_at < now-24h` subtracted from the current-24h window. Integer, signed. |

Edge cases:
- Empty DB → every `value=0`, `delta=0`.
- If `created_at` column is missing for a metric's source, fall back to `delta=0` (never raise).

**Forbidden**: adding `compliance_grade`, `compliance_score`, or any field not listed above. Production KPI cards have exactly these 6 metrics.

### 2.2 `GET /api/dashboard/vuln-trend?range=7d|30d|90d`

Grouping: `severity × DATE(created_at)`. Output series are ordered `critical, high, medium, low`.

```json
{
  "range": "30d",
  "series": [
    { "name": "critical", "data": [{"date":"2026-04-10","count":2}, …] },
    { "name": "high",     "data": […] },
    { "name": "medium",   "data": […] },
    { "name": "low",      "data": […] }
  ]
}
```

Rules:
- `range` default `30d`; invalid value → `400`.
- Each series' `data` length equals the range in days (7 / 30 / 90). Missing dates emit `count=0`.
- Severity `info` is excluded from trend.

### 2.3 `GET /api/dashboard/vuln-distribution`

Grouping: `category`. Response buckets follow the order declared in [cmdb-schema.md §2.3.1](./cmdb-schema.md#231-vulnerabilitycategory-vocabulary), except `cve` and `weak_password` are folded into `other` when the sum of `cve + weak_password < 5` to avoid visual clutter (else emitted as-is). The categories `injection / auth / xss / misconfig / exposure / other` are always present (count may be zero).

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

Rules:
- `name` is server-provided in Chinese (not localised).
- Optional `?group_by=severity` alternative: emits `critical / high / medium / low / info` buckets with the same shape.

### 2.4 `GET /api/dashboard/asset-distribution`

Grouping: `json_extract(asset.tags, '$.type')`. Buckets fixed in the order below; missing/NULL values fall into `other`.

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

### 2.5 `GET /api/dashboard/asset-cluster`

Grouping: `json_extract(asset.tags, '$.system')` × related vulnerability severity. Join: `vulnerability.asset_id = asset.id`.

```json
{
  "clusters": [
    { "system": "CRM",    "high": 3, "medium": 8, "low": 22 },
    …
  ]
}
```

Rules:
- Assets with `tags.system IS NULL` are excluded; a `logger.warning` records the skipped count per request.
- Only `high / medium / low` are reported (not critical / info) to match the stacked-bar widget.
- `critical` is folded into `high` for cluster widget purposes; per-system critical counts live in `/api/dashboard/summary` aggregate.
- Systems with zero vulnerabilities across all three levels are still emitted (all zeros) so the widget shows the full system roster.

### 2.6 `GET /api/agents?include_status=true`

Backward-compatible extension: without the flag, response is unchanged (static YAML registry). With `include_status=true`, each agent entry is enriched:

```json
{
  "agents": [
    {
      "name": "asset_discovery",
      "display_name": "资产发现智能体",
      "description": "…",
      "scoped_skills": ["…"],
      "status": "idle|running|queued|offline",
      "current_task_id": "TASK-2026-0510-014",
      "progress": null,
      "last_heartbeat_at": "2026-05-10T04:38:00+00:00"
    }
  ]
}
```

Rules:
- `status` default `offline` when the runtime is not wired (no `SubagentManager` attached, or the binary is missing); else `idle` when there is no in-flight task.
- `progress` is **always `null`** in this endpoint today. A future `ScanProgress` aggregator may populate it when `status='running'`; until then the field is emitted so the schema stays stable. (Historical prototype in webui `dashboard.ts` assumed a 0..1 float — **do not** infer that shape from this handler.)
- `last_heartbeat_at` is an **ISO-8601 UTC timestamp** (`+00:00` suffix). Client-side time-zone display is the frontend's responsibility. Sourced from the last `SubagentStatus.updated_at`; falls back to `HeartbeatService` when available.
- HTTP and WebSocket surfaces MUST stay consistent: see `secbot/channels/websocket.py::WebSocketChannel.broadcast_agent_event` — the `agent_event.agent_status` frame (§3.3 below) carries the same tuple.

---

## 3. WebSocket broadcast complements

### 3.1 `task_update`

Emitted by the scan lifecycle hooks (see [scan-lifecycle.md](./scan-lifecycle.md)) on:
- Status transition (`queued → running → completed/failed/cancelled`)
- Progress advancement (throttled to at most **1 update / 1s** per `task_id`)

Wire format:

```json
{
  "event": "task_update",
  "task_id": "TASK-2026-0510-014",
  "scan_id": "01JS…",
  "status": "running",
  "progress": 0.68,
  "kpi": { "discovered_assets": 47, "open_ports": 183, "critical_findings": 3 },
  "timestamp": "…"
}
```

### 3.2 `blackboard_update`

Emitted when scan-local counters advance. Same throttling (1/s per `chat_id`).

```json
{
  "event": "blackboard_update",
  "chat_id": "0e1b…c8",
  "stats": { "discovered_assets": 47, "open_ports": 183, "critical_findings": 3 },
  "timestamp": "…"
}
```

### 3.3 `agent_event.agent_status`

Emitted by `SubagentManager` on every expert-agent lifecycle transition (`spawn → running → done/error`). No throttling — frequency is naturally low (one frame per phase, not per token).

Frame shape (standard `agent_event` envelope used by `broadcast_agent_event`):

```json
{
  "event": "agent_event",
  "chat_id": "0e1b…c8",
  "type": "agent_status",
  "payload": {
    "type": "agent_status",
    "agent_name": "port_scan",
    "agent_status": "idle|running|queued|offline",
    "current_task_id": "task-42",
    "last_heartbeat_at": "2026-05-10T04:38:00+00:00"
  },
  "timestamp": "2026-05-10T04:38:00+00:00"
}
```

Rules:
- Payload tuple MUST mirror `/api/agents?include_status=true` row for the same `agent_name` (last-write-wins across tasks for that agent).
- `agent_name` is the logical registry key (the same string the HTTP endpoint returns); NEVER the display name.
- Client-side frontends keyed by `agent_name` (e.g. `webui/src/hooks/useAgents.ts`) patch the row in place and drop frames for unknown names (degrade-don't-crash).

### 3.4 `agent_event.blackboard_entry`

Emitted by `secbot/agent/blackboard.py::Blackboard.write()` whenever an entry is committed. The payload carries an optional `kind` auto-extracted from the leading `[tag]` prefix; see [blackboard-registry.md](./blackboard-registry.md) for the contract.

---

## 4. Query performance

On-disk SQLite with current indexes covers every aggregation in a single scan:

| Endpoint | Index used |
|----------|------------|
| summary (asset count / vuln count) | `(actor_id, severity, created_at)` on vulnerability; `(actor_id, *)` on asset |
| vuln-trend | `(actor_id, severity, created_at)` |
| vuln-distribution | `(actor_id, severity, created_at)` (scans category inline; ok for <100k rows) |
| asset-distribution | full table scan on asset (acceptable for <10k rows). If scale grows, add functional index `json_extract(tags,'$.type')`. |
| asset-cluster | join asset ↔ vulnerability on `asset_id`. Ensure `vulnerability(asset_id)` index exists. |

If any aggregation exceeds 200ms in production, introduce the in-process 10s cache (see §1) before reaching for materialised views.

---

## 5. Test expectations

`tests/api/test_dashboard.py` MUST cover:

- Empty DB → every endpoint returns the documented shape with zeroed counts.
- One scan / one asset / one vuln → single-row results with correct grouping.
- Multi-severity fixture → `vuln-trend` series lengths equal range.
- `include_status=true` vs default → two snapshots differ only in the added fields.
- `range=invalid` → 400.

---

## Origin

- `.trellis/tasks/05-10-p0-dashboard-aggregation/prd.md`
- `webui/src/gap/dashboard-data.md`
- `webui/src/data/mock/dashboard.ts` (field-by-field parity source)

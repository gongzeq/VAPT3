# Backend REST API Contract

> Complete REST API surface for the nanobot/secbot platform. Covers both the WebSocket channel's HTTP parser and the standalone aiohttp services.

---

## Overview

The backend exposes two HTTP surfaces:

1. **WebSocket Channel HTTP** (`secbot/channels/websocket.py`): The gateway's built-in HTTP parser handles REST endpoints alongside the WebSocket upgrade. **All endpoints are GET-only** due to the `websockets` library's HTTP parser limitation. Mutating operations encode actions in the URL path (e.g. `/delete`, `/archive`).

2. **aiohttp Services** (`secbot/api/server.py`, `secbot/api/agents.py`, etc.): Full HTTP verb support (GET/POST/PUT/DELETE). Used for agent CRUD, workflow builder, and the OpenAI-compatible API.

**Authentication**: All `/api/*` endpoints require `Authorization: Bearer <token>`. Tokens are obtained via `GET /webui/bootstrap` with `X-Nanobot-Auth: <secret>`.

---

## 1. Authentication & Bootstrap

### `GET /webui/bootstrap`

Mint a short-lived token + WebSocket path for the embedded UI.

**Headers**: `X-Nanobot-Auth: <shared-secret>`

**Response** `200`:
```json
{
  "token": "eyJ...",
  "ws_path": "/ws",
  "expires_in": 3600,
  "model_name": "gpt-4o",
  "workflow_api_port": 8901
}
```

**Errors**: `401` (missing/invalid secret), `503` (gateway not ready).

---

## 2. Sessions

### `GET /api/sessions`

List all websocket-channel sessions. Supports filtering, pagination, and text search.

**Query params**:
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `q` | string | — | Text search over title/preview/key |
| `archived` | `0`/`1` | — | Filter: `0`=active only, `1`=archived only, absent=all |
| `limit` | int | `50` | Page size (max 500) |
| `offset` | int | `0` | Pagination offset |

**Response** `200`:
```json
{
  "sessions": [
    {
      "key": "websocket:abc-123",
      "created_at": "2026-06-01T10:00:00Z",
      "updated_at": "2026-06-01T10:30:00Z",
      "title": "Full scan on 192.168.1.0/24",
      "preview": "Scan the subnet...",
      "archived": false
    }
  ],
  "total": 42,
  "limit": 50,
  "offset": 0
}
```

**Notes**: Only `websocket:` prefixed sessions are returned. Absolute paths are stripped.

### `GET /api/sessions/{key}/messages`

Fetch all persisted messages for a session.

**Response** `200`:
```json
{
  "key": "websocket:abc-123",
  "created_at": "2026-06-01T10:00:00Z",
  "updated_at": "2026-06-01T10:30:00Z",
  "messages": [
    {
      "role": "user",
      "content": "Scan 192.168.1.0/24",
      "timestamp": "2026-06-01T10:00:01Z",
      "media_urls": [{"url": "/api/media/sig/payload", "name": "screenshot.png"}]
    },
    {
      "role": "assistant",
      "content": "Starting full scan...",
      "timestamp": "2026-06-01T10:00:02Z",
      "tool_calls": [...],
      "sender_id": "orchestrator",
      "_kind": "agent_event",
      "agent_event": {"type": "thought", "content": "..."}
    }
  ]
}
```

**Errors**: `404` (session not found or not persisted yet).

### `GET /api/sessions/{key}/asset-auto-management`

Read/update the session-scoped managed asset ingestion switch.

**Query params**: `enabled=0|1` (omit to read, include to update).

**Response** `200`:
```json
{ "key": "websocket:abc-123", "asset_auto_management": true }
```

### `GET /api/sessions/{key}/delete`

Delete a session (unlinks the JSONL file).

**Response** `200`:
```json
{ "deleted": true }
```

### `GET /api/sessions/{key}/archive`

Toggle the archived flag.

**Query params**: `archived=0|1` (default `1`).

**Response** `200`:
```json
{ "key": "websocket:abc-123", "archived": true }
```

---

## 3. Settings

### `GET /api/settings`

Fetch current agent settings.

**Response** `200`:
```json
{
  "agent": { "model": "gpt-4o", "provider": "openai", "resolved_provider": "openai", "has_api_key": true },
  "providers": [{"name": "openai", "label": "OpenAI"}],
  "custom": { "api_base": "https://api.openai.com/v1", "api_key_masked": "sk-****abcd", "has_api_key": true },
  "provider_configs": { "openai": { "api_base": "...", "default_api_base": "...", "api_key_masked": "...", "has_api_key": true } },
  "runtime": { "config_path": "/path/to/config.json" },
  "requires_restart": false
}
```

### `GET /api/settings/update`

Update settings. **Query params**: `model`, `provider`, `api_base`. **Header**: `X-Settings-Api-Key` (API key, never in URL).

**Response** `200`: Same as `GET /api/settings`.

### `GET /api/settings/models`

Probe an OpenAI-compatible endpoint for available models.

**Query params**: `api_base` (required). **Header**: `X-Settings-Api-Key` (optional).

**Response** `200`:
```json
{ "models": ["gpt-4o", "gpt-4o-mini"] }
```

---

## 4. Commands & Prompts

### `GET /api/commands`

List quick-command slash commands.

**Response** `200`:
```json
{
  "commands": [
    { "command": "/scan", "title": "启动扫描", "description": "...", "icon": "Crosshair", "arg_hint": "<target>" }
  ]
}
```

### `GET /api/prompts`

List prompt suggestions (YAML-backed, hot-reloaded).

**Response** `200`:
```json
{
  "prompts": [
    { "id": "p1", "title": "...", "body": "...", "icon": "..." }
  ]
}
```

---

## 5. Notifications

### `GET /api/notifications`

List notifications from the in-memory ring buffer.

**Query params**: `unread=1` (filter unread), `limit` (default 50, max 500), `offset`.

**Response** `200`:
```json
{
  "items": [
    { "id": "n-001", "kind": "scan_completed", "title": "...", "body": "...", "created_at": "...", "read": false, "link": "/tasks/T-001" }
  ],
  "total": 10,
  "limit": 50,
  "offset": 0,
  "unread_count": 3
}
```

### `GET /api/notifications/read-all`

Mark all notifications as read.

**Response** `200`: `{ "updated": 3 }`

### `GET /api/notifications/{id}/read`

Mark a single notification as read.

**Response** `200`: `{ "id": "n-001", "read": true }`

---

## 6. Activity Events

### `GET /api/events`

Activity event stream (rolling 5-minute window by default).

**Query params**: `since` (ISO-8601), `limit` (default 50, max 500), `chat_id`, `category` (comma-separated).

**Response** `200`:
```json
{
  "items": [
    {
      "id": "ev-001",
      "timestamp": "2026-06-01T10:05:00Z",
      "level": "info",
      "source": "port_scan",
      "message": "Scanned 192.168.1.1:80",
      "task_id": "T-001",
      "chat_id": "abc-123",
      "agent": "port_scan",
      "step": "scan_port",
      "category": "tool_call",
      "duration_ms": 1200
    }
  ]
}
```

---

## 7. Reports

### `GET /api/reports`

List report artefacts from the `report_meta` table.

**Query params**: `range` (default `30d`), `type`, `status`, `limit` (max 500), `offset`.

**Response** `200`: See spec `backend/report-meta.md`.

### `GET /api/reports/{id}`

Single report detail.

**Response** `200`: Report metadata + download URL.

---

## 8. Agents & Skills (aiohttp)

### `GET /api/agents`

List expert-agent registry (with optional runtime status).

**Query params**: `include_status=true` (adds `status`, `current_task_id`, `progress`, `last_heartbeat_at`).

**Response** `200`:
```json
{
  "agents": [
    {
      "name": "port_scan",
      "display_name": "端口扫描",
      "description": "...",
      "scoped_skills": ["nmap_scan"],
      "max_iterations": 10,
      "available": true,
      "required_binaries": ["nmap"],
      "missing_binaries": [],
      "status": "running",
      "current_task_id": "T-001",
      "progress": 0.65,
      "last_heartbeat_at": "2026-06-01T10:05:00Z"
    }
  ]
}
```

### `GET /api/agents/{name}` — Single agent detail (includes `system_prompt`, `yaml_content`, schemas).

### `POST /api/agents` — Create agent. Body: `Partial<AgentDetail>`.

### `PUT /api/agents/{name}` — Update agent. Body: `Partial<AgentDetail>`.

### `DELETE /api/agents/{name}` — Delete agent.

### `GET /api/skills` — List skills.

### `GET /api/skills/{name}` — Skill detail (includes `content`).

### `POST /api/skills` — Create skill. Body: `{name, content}`.

### `PUT /api/skills/{name}` — Update skill. Body: `{content}`.

### `DELETE /api/skills/{name}` — Delete skill.

---

## 9. Blackboard & Assets (aiohttp)

### `GET /api/blackboard?chat_id={id}`

Blackboard entries for a chat.

**Response** `200`: `{ "chat_id": "...", "entries": [...] }`

### `GET /api/assets?chat_id={id}&since_id={n}&kind={type}`

Asset feed snapshot for a chat.

**Response** `200`:
```json
{
  "chat_id": "...",
  "entries": [{ "id": 1, "kind": "port", "agent_name": "port_scan", "payload": {...}, "created_at": 0 }],
  "latest_id": 42,
  "counts": { "port": 15, "service": 8, "vuln": 3 }
}
```

---

## 10. Dashboard

### `GET /api/dashboard/summary`

Global summary counts (assets, vulns, scans, agents_online).

### `GET /api/dashboard/vuln-trend`

Vulnerability trend time series.

### `GET /api/dashboard/vuln-distribution`

Vulnerability distribution by severity/type.

### `GET /api/dashboard/asset-distribution`

Asset distribution by type/status.

### `GET /api/dashboard/asset-cluster`

Asset clustering for visualization.

### `GET /api/dashboard/asset-risk-topology`

Asset/service/vulnerability risk relationship graph.

**Query params**: `business_system`, `subnet`, `asset_type`, `vulnerability_identity`, `candidate_status`, `recent_scan`, `focus_id`.

**Response** `200`:
```json
{
  "nodes": [{ "id": "...", "type": "asset", "label": "...", "data": {...} }],
  "edges": [{ "id": "...", "source": "...", "target": "...", "kind": "..." }],
  "focus_id": "...",
  "filters": { "business_system": null, "subnet": null }
}
```

See spec `backend/dashboard-aggregation.md` for full schema.

---

## 11. Phishing Dashboard

| Endpoint | Description |
|----------|-------------|
| `GET /api/dashboard/phishing/summary` | Aggregate counts |
| `GET /api/dashboard/phishing/stats` | Detection statistics |
| `GET /api/dashboard/phishing/history` | Detection history |
| `GET /api/dashboard/phishing/trend` | Trend time series |
| `GET /api/dashboard/phishing/top-senders` | Top phishing senders |
| `GET /api/dashboard/phishing/health` | Database health check |

---

## 12. Log Analysis Dashboard

| Endpoint | Description |
|----------|-------------|
| `GET /api/dashboard/log-analysis/latest` | Latest detection results |
| `GET /api/dashboard/log-analysis/history` | Detection history |
| `GET /api/dashboard/log-analysis/{id}/handle` | Mark as acknowledged |
| `GET /api/dashboard/log-analysis/{id}/unhandle` | Unmark acknowledgment |

---

## 13. Media

### `GET /api/media/{sig}/{payload}`

Fetch a signed media file. `sig` is HMAC over `payload`; payload decodes to a path inside `get_media_dir()`.

**Response** `200`: Raw file bytes with appropriate `Content-Type`.

**Errors**: `403` (invalid signature), `404` (file not found).

---

## 14. Workflows (aiohttp, standalone or embedded)

### CRUD

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/workflows` | List workflows |
| `POST` | `/api/workflows` | Create workflow |
| `GET` | `/api/workflows/{id}` | Get workflow detail |
| `PUT` | `/api/workflows/{id}` | Update workflow |
| `DELETE` | `/api/workflows/{id}` | Delete workflow |

### Execution

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/workflows/{id}/run` | Start a run |
| `POST` | `/api/workflows/{id}/cancel` | Cancel a run |
| `GET` | `/api/workflows/{id}/runs` | List run history |
| `GET` | `/api/workflows/{id}/runs/{runId}` | Get run detail |
| `POST` | `/api/workflows/{id}/schedule` | Set/update schedule |

### Metadata

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/workflows/_tools` | Available tool refs for `kind=tool` steps |
| `GET` | `/api/workflows/_agents` | Available agent refs for `kind=agent` steps |
| `GET` | `/api/workflows/_templates` | Workflow templates |
| `GET` | `/api/workflows/_failed-runs` | Recent failed runs |

---

## 15. OpenAI-Compatible API (aiohttp)

### `POST /v1/chat/completions`

OpenAI-compatible chat completion. Supports JSON body and `multipart/form-data` (file upload). Supports `stream: true` for SSE.

### `GET /v1/models`

List available models.

### `GET /health`

Health check.

---

## 16. WebSocket Protocol

See spec `backend/websocket-protocol.md` for the complete wire envelope.

### Client → Server (Outbound)

| Type | Payload | Description |
|------|---------|-------------|
| `new_chat` | `{}` | Request a new chat_id |
| `attach` | `{chat_id}` | Subscribe to a chat |
| `message` | `{chat_id, content, media?, webui?}` | Send a message |
| `stop` | `{chat_id}` | Cancel active turn |
| `scan.user_reply` | `{ask_id, decision, reason?}` | Approve/deny high-risk action |

### Server → Client (Inbound)

| Event | Description |
|-------|-------------|
| `ready` | Initial chat_id assigned |
| `attached` | Chat subscription confirmed (+ `active_turn` flag) |
| `message` | Complete assistant message (may include `buttons`, `media_urls`, `kind`) |
| `delta` | Streaming text chunk |
| `stream_end` | Stream segment boundary |
| `turn_end` | Turn complete (+ optional `usage`) |
| `session_updated` | Session metadata changed |
| `agent_event` | Agent lifecycle event (14 types) |
| `activity_event` | Global activity broadcast |
| `error` | Error notification |

---

## Implementation Notes

1. **GET-only constraint**: The `websockets` HTTP parser does not support POST/PUT/DELETE. All websocket-channel endpoints use GET with actions encoded in the path.
2. **CORS**: The standalone workflow aiohttp app includes CORS middleware (`Access-Control-Allow-Origin: *`) for cross-origin calls from the Vite dev server.
3. **Token lifecycle**: Tokens expire after `expires_in` seconds. The frontend auto-refreshes on 401 via `_refreshToken()` → `fetchBootstrap(savedSecret)`.
4. **Session scoping**: `/api/sessions/*` endpoints only accept `websocket:` prefixed keys — CLI/Slack/Lark sessions are intentionally excluded from the WebUI.
5. **Media signing**: `/api/media/{sig}/{payload}` URLs are HMAC-signed to prevent path traversal. Signatures are generated server-side when replaying session messages.

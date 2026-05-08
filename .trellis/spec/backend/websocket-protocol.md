# WebSocket Protocol

> Wire contract between `webui/` and `secbot/api/websocket.py`.
> Owned jointly by backend (server emitter) and frontend (client consumer); changes require updates on **both** sides in the same PR.

---

## 1. Endpoint

```
ws://<host>:<port>/ws
```

Auth: same bearer token as REST API, sent as `Sec-WebSocket-Protocol: bearer.<token>` (sub-protocol field) — query string tokens are forbidden (they leak into proxy logs).

One WS connection per browser tab. Multiplexing across scans happens via `scan_id` in the message envelope.

---

## 2. Message Envelope

All frames are JSON, single message per frame. Envelope:

```json
{
  "v": 1,
  "type": "<event_type>",
  "scan_id": "<ULID|null>",
  "ts": "2026-05-07T10:00:00.000Z",
  "data": { ... }
}
```

| Field | Required | Notes |
|-------|----------|-------|
| `v` | yes | Protocol version, currently `1`. Mismatched version → server closes with code 4001. |
| `type` | yes | Event type, see §3 / §4 |
| `scan_id` | no | Required for scan-bound events; null for connection-level (`hello`, `ping`). |
| `ts` | yes | ISO-8601 UTC, millisecond precision |
| `data` | yes | Type-specific payload |

---

## 3. Server → Client Events

Mirrors [scan-lifecycle.md §3 + §4](./scan-lifecycle.md#3-bus-events). Backend `secbot/api/websocket.py` translates bus events 1:1 into WS frames.

| `type` | When | `data` |
|--------|------|--------|
| `hello` | Right after auth succeeds | `{server_version, supported_versions: [1], actor_id}` |
| `scan.created` | Bus event | per [scan-lifecycle.md](./scan-lifecycle.md#3-bus-events) |
| `scan.started` | Bus event | per scan-lifecycle |
| `scan.awaiting_user` | Bus event | per scan-lifecycle, drives the AlertDialog (see [component-patterns.md §3](../frontend/component-patterns.md)) |
| `scan.completed` / `scan.failed` / `scan.cancelled` | Terminal | per scan-lifecycle |
| `agent.token` | LLM streaming | `{message_id, token, role}` |
| `tool.call` | Orchestrator/Expert dispatch | `{message_id, tool_call_id, tool_name, args, risk_level}` |
| `tool.progress` | Skill progress | `{tool_call_id, percent: 0-100, message}` |
| `tool.result` | Skill done | `{tool_call_id, summary_json, raw_log_path, duration_ms}` |
| `tool.error` | Skill failure | `{tool_call_id, error_type, message}` |
| `agent.thought` | Orchestrator reasoning step (optional; non-breaking, PR3) | `{message_id, step_id, tool_call_id, title, icon?, parent_step_id?, tokens?, status: "running"\|"ok"\|"error", duration_ms?, next_action?}` |
| `pong` | Reply to `ping` | `{}` |

Ordering guarantee: events for a given `scan_id` are delivered in the order they were emitted on the bus. Cross-scan ordering is unspecified.

### 3.1 Reserved tool name `__thought__` (PR3)

Backends MAY surface orchestrator reasoning through the **existing** `tool.call` / `tool.progress` / `tool.result` triplet by setting `tool_name === "__thought__"`. No new event type is required, and no frontend upgrade is needed beyond registering the `<AgentThoughtChain>` renderer at `SKILL_RENDERERS["__thought__"]` (see [frontend component-patterns.md §1.3](../frontend/component-patterns.md#13-reasoning--thought-stream-pr3--05-07-ocean-tech-frontend-r6)).

**Wire shapes** (canonical, mirror the frontend contract):

- `tool.call` `args`: `{ step_id: string; title: string; icon?: "brain" | "wrench" | "search" | "filetext"; parent_step_id?: string }`
- `tool.progress` `data.message` (free-form) carries incremental reasoning tokens; cumulative `percent` is unused for `__thought__` (set to 0 or omit).
- `tool.result` `summary_json`: `{ status: "ok" | "error"; tokens: string; duration_ms: number; next_action?: string }`. `raw_log_path` is OPTIONAL (reasoning rarely has a raw log).
- `risk_level` MUST be `"safe"` on `__thought__` — thought emission never triggers the high-risk AlertDialog.

**When to prefer `agent.thought` over `tool.call(__thought__)`**: if the orchestrator implementation already routes other messages via a typed reasoning bus (e.g. CoT scaffolding) and does not want to conflate with the tool-invocation pipeline. Both paths MUST render identically on the frontend; the UI is deliberately source-agnostic.

---

## 4. Client → Server Events

| `type` | Purpose | `data` |
|--------|---------|--------|
| `ping` | Keepalive (every 25s if no traffic) | `{}` |
| `scan.user_reply` | User responded to `scan.awaiting_user` | `{ask_id, decision: "approve"\|"deny", reason?: string}` |
| `scan.cancel` | User clicked Stop | `{scan_id, reason?: string}` |
| `subscribe` | Replay buffered events for an existing scan | `{scan_id, since_ts?: string}` |

Client-initiated message creation (sending a chat prompt) goes via `POST /scans` REST, NOT through WS. WS is **delivery only** for streaming.

---

## 5. Connection Management

- Server pings on idle every 30s; client pings every 25s. Two missed pings → server closes with 4002 (timeout); client must reconnect.
- On reconnect, client SHOULD send `subscribe` with `since_ts` for each in-flight scan to replay events. Server keeps a 5-minute ring buffer per scan.
- Backpressure: if a client falls behind (>1MB queued), server closes with 4003 (slow consumer). Client must reconnect and re-subscribe.
- Close codes:
  | Code | Meaning |
  |------|---------|
  | 1000 | Normal closure |
  | 4001 | Protocol version mismatch |
  | 4002 | Idle timeout |
  | 4003 | Slow consumer |
  | 4401 | Unauthorized |
  | 4403 | actor_id mismatch (token does not own this WS) |

---

## 6. Versioning

- The `v` field locks the wire format. Adding a new event `type` is non-breaking. Changing the shape of an existing `data` payload IS breaking — bump to `v=2`, server announces both via `hello.supported_versions`, frontend negotiates.
- Removing an event type requires deprecation across one minor version with a `Deprecation` header in `hello.data`.
- Added event types since `v=1` (non-breaking; frontend MUST gracefully ignore unknown `type` values):
  - `agent.thought` — PR3 of 05-07-ocean-tech-frontend. See §3 + §3.1.

---

## Origin

Source: `.trellis/tasks/05-07-cybersec-agent-platform/prd.md` §"WebSocket" + cross-references with [scan-lifecycle.md](./scan-lifecycle.md) and [component-patterns.md](../frontend/component-patterns.md).

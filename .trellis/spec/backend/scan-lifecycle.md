# Scan Lifecycle

> Defines the state machine of a `scan` row and the events it MUST emit on the bus.
> Implementation: `secbot/scan/lifecycle.py` + `secbot/bus/events.py`.

---

## 1. State Machine

```
            ┌──────────────────────────────────────────┐
            │                                          ▼
queued ──► running ──► awaiting_user ──► running ──► completed
   │           │                                       
   │           └────────────────────────────────────► failed
   │                                                  
   └────────────────────────────────────────────────► cancelled
```

| State | Entry condition | Allowed exits |
|-------|-----------------|---------------|
| `queued` | Scan row created via `POST /scans` or CLI | `running`, `cancelled` |
| `running` | Orchestrator first tool_call dispatched | `awaiting_user`, `completed`, `failed`, `cancelled` |
| `awaiting_user` | A `critical` skill issued `ask_user` (see [high-risk-confirmation.md](./high-risk-confirmation.md)) | `running` (after user reply), `cancelled` |
| `completed` | Orchestrator emits final assistant message AND no pending tool_calls | terminal |
| `failed` | Unhandled exception bubbled out of Orchestrator loop | terminal |
| `cancelled` | User clicked Stop / sent `DELETE /scans/<id>` / Ctrl-C | terminal |

Illegal transitions raise `InvalidScanTransition` and are logged at ERROR.

---

## 2. Persistence Rules

- The `scan.status` column is the **single source of truth**. All transitions go through `secbot/scan/lifecycle.py::transition(scan_id, to_state)`.
- `started_at` set on first `queued → running`.
- `finished_at` set on entry to any terminal state.
- `error` set on entry to `failed`; cleared on every other transition.
- Transitions are persisted in the same SQL transaction that emits the corresponding bus event — partial state is forbidden.

---

## 3. Bus Events

Each transition emits one event to the in-process bus. Event payload schema is part of this contract.

| Event | Trigger | Payload |
|-------|---------|---------|
| `scan.created` | Row inserted (`queued`) | `{scan_id, target, scope_json, actor_id, created_at}` |
| `scan.started` | `queued → running` | `{scan_id, started_at}` |
| `scan.awaiting_user` | `running → awaiting_user` | `{scan_id, ask_id, prompt, risk_level, command_preview}` |
| `scan.user_replied` | `awaiting_user → running` | `{scan_id, ask_id, decision: "approve"\|"deny", reason?}` |
| `scan.completed` | `running → completed` | `{scan_id, finished_at, severity_counts, asset_count}` |
| `scan.failed` | `running → failed` | `{scan_id, finished_at, error}` |
| `scan.cancelled` | `* → cancelled` | `{scan_id, finished_at, reason: "user"\|"timeout"\|"shutdown"}` |

All events also carry `actor_id`. Subscribers MUST filter by `actor_id` (consistent with the CMDB rule).

---

## 4. Streaming Sub-Events

In addition to lifecycle events, the Orchestrator and skills emit **streaming progress** events bound to a `scan_id`:

| Event | Source | Notes |
|-------|--------|-------|
| `agent.token` | LLM streaming | One per token chunk |
| `tool.call` | Orchestrator / Expert | Emitted before invocation |
| `tool.progress` | Skill | Emitted by skill via `ctx.report_progress(percent, message)` |
| `tool.result` | Skill | After completion, includes `summary_json` |
| `tool.error` | Skill / Sandbox | Includes error type and message |

Streaming events are **not** persisted — they are best-effort fan-out. State recovery after a server restart relies on the lifecycle events + CMDB rows, not streaming events.

---

## 5. Cancellation Semantics

- A cancellation request MUST cause:
  1. Immediate `scan.cancelled` event with `reason="user"`.
  2. Termination of the in-flight subprocess via the sandbox (SIGTERM, then SIGKILL after 5s) — see [tool-invocation-safety.md §4](./tool-invocation-safety.md#4-timeout--cancellation).
  3. Rollback of any **uncommitted** CMDB writes; committed writes from earlier turns are preserved.
- Cancelling an already-terminal scan is a no-op; the API returns `409 Conflict`.

---

## 6. Resume Semantics (Future)

Out of scope for v1: there is no resume from `failed` or `cancelled`. The user must start a new scan. This is documented here so we DO NOT build half-resume support that would constrain a future redesign.

---

## Origin

Source: `.trellis/tasks/05-07-cybersec-agent-platform/prd.md` §"Scan lifecycle" + ADR-004 (single-source-of-truth state column).

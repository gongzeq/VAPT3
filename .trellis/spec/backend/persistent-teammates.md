# Persistent Teammates

> Contract for durable teammate identity, JSONL mailboxes, and manual teammate lifecycle.
> Implementation: `secbot/agent/teammate.py`, `secbot/agent/tools/teammate.py`, wired from `secbot/agent/loop.py`.

---

## Scenario: Durable Teammate Communication

### 1. Scope / Trigger

- Trigger: teammate communication adds file-backed infra under `.team/`, new orchestrator tools, and a durable lifecycle state machine.
- Scope: local single-process runtime. Multi-process OS file locking, autonomous idle polling, and UI/API teammate management pages are out of scope for the MVP.
- Architectural rule: persistent teammates are a sidecar coordination mechanism. They do not replace one-shot expert agents, the blackboard, or the two-layer orchestrator -> expert -> skill execution model.

### 2. Signatures

```python
# secbot/agent/teammate.py
TEAM_STATUS_IDLE = "idle"
TEAM_STATUS_WORKING = "working"
TEAM_STATUS_SHUTDOWN = "shutdown"

def normalize_teammate_name(name: str) -> str: ...

class TeamMessageBus:
    def __init__(self, workspace: Path) -> None: ...
    def inbox_path(self, name: str) -> Path: ...
    def ensure_inbox(self, name: str) -> Path: ...
    async def send(
        self,
        *,
        sender: str,
        to: str,
        content: str,
        msg_type: str = "message",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...
    async def read_inbox(self, name: str) -> list[dict[str, Any]]: ...

class TeamConfigStore:
    def list(self) -> list[TeammateRecord]: ...
    def get(self, name: str) -> TeammateRecord | None: ...
    def upsert(..., status: str, current_task: str | None = None, ...) -> TeammateRecord: ...
    def update_status(..., status: str, current_task: str | None = None, ...) -> TeammateRecord: ...
    def reset_working_to_idle(self) -> list[TeammateRecord]: ...

class TeammateManager:
    async def spawn(self, *, name: str, role: str, task: str | None = None) -> TeammateRecord: ...
    async def list_teammates(self) -> list[TeammateRecord]: ...
    async def send(..., sender: str, to: str, content: str, msg_type: str = "message", ...) -> dict[str, Any]: ...
    async def read_inbox(self, name: str) -> list[dict[str, Any]]: ...
    async def shutdown(self, name: str) -> TeammateRecord: ...
    async def wait_for_idle(self, name: str, timeout: float = 5.0) -> TeammateRecord: ...
```

Orchestrator tool names:

```
spawn_teammate
list_teammates
send_teammate_message
read_teammate_inbox
shutdown_teammate
```

### 3. Contracts

- Storage root is `<workspace>/.team/`.
- Durable roster is `<workspace>/.team/config.json` with shape:

```json
{
  "team_name": "default",
  "members": [
    {
      "name": "alice",
      "role": "analyst",
      "status": "idle",
      "created_at": 1715600000.0,
      "updated_at": 1715600001.0,
      "current_task": null,
      "last_result": "summary text",
      "last_error": null
    }
  ]
}
```

- Inbox path is `<workspace>/.team/inbox/<name>.jsonl`.
- `send()` appends exactly one JSON object per line:

```json
{
  "type": "message",
  "from": "orchestrator",
  "to": "alice",
  "content": "check target 10.0.0.1",
  "timestamp": 1715600000.0,
  "metadata": {}
}
```

- `read_inbox(name)` is drain-on-read: it returns valid JSON rows in file order and clears the file before returning.
- Teammate names are canonical lowercase names matching `^[a-z0-9][a-z0-9_.-]{0,63}$`; config keys and inbox filenames use the normalized name.
- Manual lifecycle is `spawn -> working -> idle -> working -> ... -> shutdown`.
- A teammate run uses a fresh `AgentRunSpec.initial_messages` list and `session_key="teammate:<name>"`. Its internal messages are process-local and are not appended to the parent chat session.
- Stale `working` records found at manager startup are reconciled to `idle` with `current_task=null` and a recovery `last_error`.
- `shutdown_teammate` marks the durable status as `shutdown` and blocks future assignments. It is not a force-cancel primitive for an already running Python thread.

### 4. Validation & Error Matrix

| Condition | Result |
|---|---|
| Invalid teammate name | `ValueError` and tool returns `Error: ...` |
| Empty role on spawn | `ValueError` and tool returns `Error: role cannot be empty` |
| Empty message content | `ValueError` and tool returns `Error: message content cannot be empty` |
| Send to unknown teammate except `orchestrator` | `KeyError` and tool returns `Error: unknown teammate: <name>` |
| Spawn an already working teammate | `RuntimeError` and tool returns `Error: teammate '<name>' is already working` |
| Spawn a shutdown teammate | `RuntimeError` and tool returns `Error: teammate '<name>' is shutdown` |
| Read malformed JSONL row | Skip the row, log warning, continue draining valid rows |
| Unknown teammate shutdown | `KeyError` and tool returns `Error: unknown teammate: <name>` |
| Process restart with `working` in config | Convert record to `idle`, clear `current_task`, preserve identity |

### 5. Good / Base / Bad Cases

- Good: use `delegate_task` for disposable expert work where only a summary should return to the orchestrator.
- Good: use `spawn_teammate` only when durable mailbox state or cross-turn teammate identity is required.
- Base: a teammate reads its own inbox via `read_teammate_inbox`; orchestrator may read named inboxes for manual inspection.
- Bad: treating `.team/inbox/*.jsonl` as chat history. It is a drain-on-read mailbox, not a transcript.
- Bad: exposing teammate tools to operational expert agents. They belong to the orchestrator coordination surface only.
- Bad: assuming `shutdown_teammate` kills an active run. It only persists shutdown state for future assignments in this MVP.

### 6. Tests Required

- Mailbox append creates `.team/inbox/<name>.jsonl` and writes one valid JSON object per line.
- `read_inbox()` returns unread rows in order and clears the file.
- `TeamConfigStore` persists name, role, status, current task, last result, and last error across store instances.
- Manager startup reconciles stale `working` records to `idle`.
- Deterministic lifecycle test covers `spawn -> working -> idle -> working -> shutdown` without a real model call.
- Tool-surface test verifies orchestrator registers teammate tools and operational expert loops do not receive them.
- One-shot subagent isolation test verifies parent session receives only the child summary, not child intermediate tool messages.

### 7. Wrong vs Correct

#### Wrong

```python
# BAD: teammate history is appended to the parent conversation.
parent_messages.extend(child_result.messages)
```

#### Correct

```python
# Only the summary/result crosses back to the parent.
parent_messages.append({"role": "user", "content": child_result.final_content})
```

#### Wrong

```python
# BAD: mailbox read leaves messages in place, causing duplicate processing.
messages = [json.loads(line) for line in inbox.read_text().splitlines()]
return messages
```

#### Correct

```python
messages = bus.read_inbox("alice")  # valid rows returned, inbox file cleared
```

---

## Origin

- `.trellis/tasks/05-16-persistent-teammate-communication/prd.md`
- `.trellis/tasks/05-16-persistent-teammate-communication/research/reference-team-model.md`
- `.trellis/tasks/05-16-persistent-teammate-communication/research/current-code.md`
